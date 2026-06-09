"""
Circuit Breaker + Bulkhead 弹性工程模块

- Circuit Breaker (熔断器): 外部依赖连续失败时快速失败，防止资源耗尽和级联故障
  状态机: CLOSED → (N次失败) → OPEN → (冷却后) → HALF_OPEN → (成功) → CLOSED
- Bulkhead (舱壁隔离): 为每个 LLM Provider 分配独立的并发信号量，
  一个 Provider 故障不影响其他 Provider

参考: Netflix Hystrix / Resilience4j
"""
import asyncio
import time
import logging
from collections import deque, defaultdict
from enum import Enum
from typing import Dict, Callable, Any, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """熔断器打开时抛出，表示请求被快速拒绝。"""
    def __init__(self, provider: str, retry_after: float):
        self.provider = provider
        self.retry_after = retry_after
        super().__init__(f"Circuit breaker OPEN for provider '{provider}', retry after {retry_after:.0f}s")


class CircuitBreaker:
    """
    Circuit Breaker 熔断器

    Args:
        failure_threshold: 滑动窗口内连续失败多少次触发熔断
        recovery_timeout: 熔断多少秒后进入 HALF_OPEN 试探
        half_open_max: HALF_OPEN 状态最多放行多少个探测请求
        window_size: 滑动窗口大小
        timeout: 单次调用超时（秒）
    """
    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max: int = 3,
        window_size: int = 10,
        timeout: float = 120.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max
        self.timeout = timeout
        self.state = CircuitState.CLOSED
        self.failures = deque(maxlen=window_size)
        self.last_failure_time: float = 0
        self.half_open_calls: int = 0
        self._lock = asyncio.Lock()

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        async with self._lock:
            self._maybe_transition()

        if self.state == CircuitState.OPEN:
            retry_after = self.recovery_timeout - (time.time() - self.last_failure_time)
            raise CircuitOpenError(self.name, max(0, retry_after))

        if self.state == CircuitState.HALF_OPEN:
            async with self._lock:
                if self.half_open_calls >= self.half_open_max:
                    raise CircuitOpenError(self.name, self.recovery_timeout)
                self.half_open_calls += 1

        try:
            result = await asyncio.wait_for(func(*args, **kwargs), timeout=self.timeout)
            self._on_success()
            return result
        except asyncio.TimeoutError:
            self._on_failure()
            raise
        except (ConnectionError, OSError) as e:
            self._on_failure()
            raise
        except Exception as e:
            err_name = type(e).__name__.lower()
            if any(kw in err_name for kw in ("timeout", "connect", "refused", "reset", "api")):
                self._on_failure()
            raise

    def _maybe_transition(self):
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                logger.info(f"Circuit [{self.name}]: OPEN → HALF_OPEN")

    def _on_success(self):
        self.failures.append(False)
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            logger.info(f"Circuit [{self.name}]: HALF_OPEN → CLOSED (recovered)")

    def _on_failure(self):
        self.failures.append(True)
        self.last_failure_time = time.time()
        recent = sum(1 for f in self.failures if f)
        if recent >= self.failure_threshold and self.state != CircuitState.OPEN:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit [{self.name}]: → OPEN ({recent} failures in window)")

    @property
    def stats(self) -> dict:
        total = len(self.failures)
        fails = sum(1 for f in self.failures if f)
        return {
            "name": self.name,
            "state": self.state.value,
            "failures_in_window": fails,
            "window_size": total,
            "threshold": self.failure_threshold,
        }


class BulkheadIsolation:
    """
    Bulkhead 舱壁隔离 — 为每个 Provider 分配独立的并发信号量。

    一个慢 Provider 最多占用 max_concurrent 个并发槽位，
    不会影响其他 Provider 的可用性。
    """
    def __init__(self, max_concurrent_per_provider: int = 10, acquire_timeout: float = 5.0):
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._max = max_concurrent_per_provider
        self._acquire_timeout = acquire_timeout

    def _get_semaphore(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._semaphores:
            self._semaphores[provider] = asyncio.Semaphore(self._max)
        return self._semaphores[provider]

    async def call(self, provider: str, func: Callable, *args, **kwargs) -> Any:
        sem = self._get_semaphore(provider)
        try:
            await asyncio.wait_for(sem.acquire(), timeout=self._acquire_timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"Provider '{provider}' 并发已满 ({self._max})，请稍后重试"
            )
        try:
            return await func(*args, **kwargs)
        finally:
            sem.release()

    @property
    def stats(self) -> dict:
        return {
            name: {
                "available": sem._value,
                "max": self._max,
                "in_use": self._max - sem._value,
            }
            for name, sem in self._semaphores.items()
        }


# ---------------------------------------------------------------------------
# 全局实例
# ---------------------------------------------------------------------------
_circuit_breakers: Dict[str, CircuitBreaker] = {}
_bulkhead = BulkheadIsolation(max_concurrent_per_provider=10)


def get_circuit_breaker(provider: str) -> CircuitBreaker:
    if provider not in _circuit_breakers:
        _circuit_breakers[provider] = CircuitBreaker(name=provider)
    return _circuit_breakers[provider]


async def call_llm_resilient(provider: str, func: Callable, *args, **kwargs) -> Any:
    """
    弹性 LLM 调用入口：Circuit Breaker + Bulkhead 双重防护。

    使用方式:
        result = await call_llm_resilient("openai", client.chat, messages=messages)
    """
    breaker = get_circuit_breaker(provider)

    async def guarded():
        return await breaker.call(func, *args, **kwargs)

    return await _bulkhead.call(provider, guarded)


def get_all_circuit_stats() -> dict:
    return {
        "circuit_breakers": {name: cb.stats for name, cb in _circuit_breakers.items()},
        "bulkhead": _bulkhead.stats,
    }
