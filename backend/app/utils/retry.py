"""
重试装饰器 — Decorrelated Jitter + Circuit Breaker 联动

Decorrelated Jitter (AWS 推荐): delay = min(cap, random(base, prev_delay * 3))
比 Full Jitter / Equal Jitter 在高并发下分散效果更好。
"""
import asyncio
import random
import logging
from functools import wraps
from typing import Callable, TypeVar, Optional
from time import sleep

logger = logging.getLogger(__name__)

T = TypeVar('T')


def async_retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    max_delay: float = 30.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable] = None,
    jitter: str = "decorrelated",
):
    """
    异步重试装饰器 — 支持 Decorrelated Jitter

    Args:
        max_attempts: 最大尝试次数
        delay: 初始延迟（秒）
        max_delay: 最大延迟上限（秒）
        backoff: 延迟倍数（仅 jitter='none' 时使用）
        exceptions: 需要重试的异常类型
        on_retry: 重试时的回调函数
        jitter: 抖动策略 — 'decorrelated'(推荐) / 'full' / 'none'
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        if on_retry:
                            on_retry(e, attempt)

                        if jitter == "decorrelated":
                            current_delay = min(max_delay, random.uniform(delay, current_delay * 3))
                        elif jitter == "full":
                            current_delay = random.uniform(0, min(max_delay, delay * (backoff ** (attempt - 1))))
                        else:
                            current_delay = min(max_delay, current_delay * backoff)

                        logger.warning(
                            f"{func.__name__} 失败 (尝试 {attempt}/{max_attempts}): {e}. "
                            f"{current_delay:.2f}秒后重试 (jitter={jitter})..."
                        )
                        await asyncio.sleep(current_delay)
                    else:
                        logger.error(f"{func.__name__} 最终失败: {e}")

            raise last_exception
        return wrapper
    return decorator


def sync_retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    max_delay: float = 30.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable] = None,
    jitter: str = "decorrelated",
):
    """
    同步重试装饰器 — 支持 Decorrelated Jitter
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        if on_retry:
                            on_retry(e, attempt)

                        if jitter == "decorrelated":
                            current_delay = min(max_delay, random.uniform(delay, current_delay * 3))
                        elif jitter == "full":
                            current_delay = random.uniform(0, min(max_delay, delay * (backoff ** (attempt - 1))))
                        else:
                            current_delay = min(max_delay, current_delay * backoff)

                        logger.warning(
                            f"{func.__name__} 失败 (尝试 {attempt}/{max_attempts}): {e}. "
                            f"{current_delay:.2f}秒后重试 (jitter={jitter})..."
                        )
                        sleep(current_delay)
                    else:
                        logger.error(f"{func.__name__} 最终失败: {e}")

            raise last_exception
        return wrapper
    return decorator
