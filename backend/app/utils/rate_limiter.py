"""
多层限流架构 — Sliding Window Log + Concurrent Limiter + Local Token Bucket 降级

- Sliding Window Log: Redis Sorted Set 精确计数，无固定窗口边界绕过
- Concurrent Limiter: 限制单用户同时进行的流式连接数
- Local Token Bucket: Redis 不可用时的本地降级限流
- 全程 async，不阻塞事件循环
"""
from functools import wraps
from typing import Callable, Optional, Dict
from fastapi import Request, HTTPException, status
import asyncio
import time
import logging
from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lua 脚本：Sliding Window Log（原子操作，一次 RTT）
# ---------------------------------------------------------------------------
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])

-- 移除窗口外的旧记录
redis.call('ZREMRANGEBYSCORE', key, 0, now - window_ms)

-- 当前窗口内的请求数
local count = redis.call('ZCARD', key)
if count < limit then
    -- 放行：记录本次请求（member 用 now:random 保证唯一）
    redis.call('ZADD', key, now, now .. ':' .. math.random(1000000))
    redis.call('PEXPIRE', key, math.ceil(window_ms / 1000) * 1000 + 1000)
    return {0, limit - count - 1, 0}  -- {放行, 剩余配额, 0}
end

-- 限流：计算最早记录的过期时间作为 Retry-After
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local retry_after = 0
if oldest and #oldest >= 2 then
    retry_after = math.ceil((tonumber(oldest[2]) + window_ms - now) / 1000)
end
return {1, 0, retry_after}  -- {拒绝, 0, retry_after秒}
"""

# ---------------------------------------------------------------------------
# Lua 脚本：Concurrent Limiter（限制同时进行的连接数）
# ---------------------------------------------------------------------------
_CONCURRENT_LUA = """
local key = KEYS[1]
local max_concurrent = tonumber(ARGV[1])
local request_id = ARGV[2]
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

-- 清理过期的连接记录
redis.call('ZREMRANGEBYSCORE', key, 0, now)

-- 当前并发数
local count = redis.call('ZCARD', key)
if count < max_concurrent then
    -- 放行：注册本连接（score = 过期时间）
    redis.call('ZADD', key, now + ttl, request_id)
    redis.call('EXPIRE', key, ttl + 60)
    return 0  -- 放行
end
return 1  -- 拒绝
"""


# ---------------------------------------------------------------------------
# Local Token Bucket（Redis 不可用时的降级限流）
# ---------------------------------------------------------------------------
class LocalTokenBucket:
    """本地令牌桶 — Redis 不可用时的降级限流。

    每个 key 独立维护令牌数和最后填充时间。
    """
    def __init__(self):
        self._buckets: Dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, rate: float, capacity: int) -> bool:
        async with self._lock:
            now = time.monotonic()
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = {"tokens": capacity, "last": now}
                self._buckets[key] = bucket

            elapsed = now - bucket["last"]
            bucket["tokens"] = min(capacity, bucket["tokens"] + elapsed * rate)
            bucket["last"] = now

            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                return True
            return False


_local_bucket = LocalTokenBucket()
_lua_scripts: Dict[str, object] = {}


async def _get_lua_scripts(redis_client):
    if "sliding_window" not in _lua_scripts:
        _lua_scripts["sliding_window"] = redis_client.register_script(_SLIDING_WINDOW_LUA)
        _lua_scripts["concurrent"] = redis_client.register_script(_CONCURRENT_LUA)
    return _lua_scripts


# ---------------------------------------------------------------------------
# Rate Limit 装饰器
# ---------------------------------------------------------------------------
def rate_limit(
    requests_per_minute: int = 60,
    by: str = "user",
    concurrent: Optional[int] = None,
    concurrent_ttl: int = 600,
):
    """
    API 限流装饰器 — Sliding Window Log + 可选 Concurrent Limiter

    Args:
        requests_per_minute: 每分钟最大请求数
        by: 限流维度 — 'user'（按用户ID）或 'ip'（按客户端IP）
        concurrent: 最大并发连接数（None = 不限并发）
        concurrent_ttl: 并发连接最大生命周期（秒，防泄漏）
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            if not getattr(settings, 'rate_limit_enabled', True):
                return await func(request, *args, **kwargs)

            # --- 确定限流 key ---
            if by == "ip":
                client_id = request.client.host if request.client else "unknown"
            else:
                client_id = "unknown"
                if hasattr(request.state, 'user') and request.state.user:
                    client_id = f"u{request.state.user.id}"
                elif request.client:
                    client_id = request.client.host

            rate_key = f"rl:{func.__name__}:{client_id}"

            # --- 尝试 Redis 限流 ---
            try:
                from app.utils.optimized_redis import get_async_redis_client
                redis_client = get_async_redis_client()
                scripts = await _get_lua_scripts(redis_client)

                now_ms = int(time.time() * 1000)
                window_ms = 60_000

                result = await scripts["sliding_window"](
                    keys=[rate_key],
                    args=[now_ms, window_ms, requests_per_minute],
                )
                rejected, remaining, retry_after = int(result[0]), int(result[1]), int(result[2])

                if rejected:
                    logger.warning(f"限流触发: {client_id} on {func.__name__}, retry_after={retry_after}s")
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"请求过于频繁，请 {retry_after} 秒后重试",
                        headers={"Retry-After": str(retry_after)},
                    )

                # --- Concurrent Limiter（可选）---
                request_id = None
                if concurrent is not None:
                    import uuid
                    request_id = str(uuid.uuid4())
                    concurrent_key = f"cc:{func.__name__}:{client_id}"
                    now_s = time.time()

                    cc_result = await scripts["concurrent"](
                        keys=[concurrent_key],
                        args=[concurrent, request_id, now_s, concurrent_ttl],
                    )
                    if int(cc_result) == 1:
                        logger.warning(f"并发限制触发: {client_id} on {func.__name__}, max={concurrent}")
                        raise HTTPException(
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=f"同时进行的请求过多（上限 {concurrent} 个），请等待当前请求完成",
                        )

                try:
                    return await func(request, *args, **kwargs)
                finally:
                    if request_id and concurrent is not None:
                        try:
                            concurrent_key = f"cc:{func.__name__}:{client_id}"
                            await redis_client.zrem(concurrent_key, request_id)
                        except Exception:
                            pass

            except HTTPException:
                raise
            except Exception as e:
                # Redis 不可用 → 降级到本地 Token Bucket
                logger.warning(f"Redis 限流不可用，降级到本地 Token Bucket: {e}")
                rate = requests_per_minute / 60.0
                allowed = await _local_bucket.acquire(rate_key, rate, requests_per_minute)
                if not allowed:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="请求过于频繁，请稍后再试",
                    )
                return await func(request, *args, **kwargs)

        return wrapper
    return decorator
