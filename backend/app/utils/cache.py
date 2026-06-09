"""
缓存工具 — 带 Singleflight 防击穿 + Tag-Based Invalidation + XFetch 概率续期

- Singleflight: 同一 key 的并发 miss 只执行一次后端调用，其余 await 共享结果
- XFetch: 在 TTL 临近时概率性提前刷新，避免热点 key 过期瞬间的 Stampede
- Tag-Based Invalidation: 通过 Redis Set 精确追踪 key，替代 O(N) 的 KEYS 扫描
- UNLINK: 异步删除大 key，不阻塞 Redis 主线程
"""
from functools import wraps
import json
import hashlib
import asyncio
import math
import random
import time
import inspect
from typing import Callable, Any, Dict, List, Optional
import logging
from app.config import settings
from app.utils.optimized_redis import get_redis_pool
import redis

logger = logging.getLogger(__name__)

_CACHE_VERSION = 1


def _stable_cache_key(prefix: str, func_name: str, args: tuple, kwargs: dict) -> str:
    key_data = json.dumps(
        {"a": list(args), "k": kwargs},
        sort_keys=True,
        default=str,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(key_data.encode("utf-8")).hexdigest()[:20]
    return f"v{_CACHE_VERSION}:{prefix}:{func_name}:{digest}"


# ---------------------------------------------------------------------------
# Singleflight: 同 key 并发只执行一次
# ---------------------------------------------------------------------------
class Singleflight:
    """同一 key 的并发调用只执行一次，其余搭便车共享结果。

    类似 Go 标准库 singleflight.Group。
    """
    def __init__(self):
        self._flights: Dict[str, asyncio.Future] = {}

    async def do(self, key: str, fn: Callable):
        if key in self._flights:
            return await self._flights[key]

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._flights[key] = future

        try:
            result = await fn()
            future.set_result(result)
            return result
        except Exception as e:
            future.set_exception(e)
            raise
        finally:
            self._flights.pop(key, None)


_singleflight = Singleflight()


# ---------------------------------------------------------------------------
# XFetch entry 序列化
# ---------------------------------------------------------------------------
def _pack_xfetch_entry(value: Any, ttl: int, compute_time: float) -> str:
    entry = {
        "v": value,
        "t": time.time() + ttl,  # 逻辑过期时间
        "d": compute_time,        # 上次计算耗时
    }
    return json.dumps(entry, default=str, ensure_ascii=False)


def _unpack_xfetch_entry(raw: str):
    entry = json.loads(raw)
    return entry["v"], entry["t"], entry.get("d", 0.5)


# ---------------------------------------------------------------------------
# 缓存装饰器
# ---------------------------------------------------------------------------
def cache_result(ttl: int = 3600, key_prefix: str = "", tags: Optional[List[str]] = None, beta: float = 1.0):
    """
    缓存装饰器 — 带 Singleflight 防击穿 + XFetch 概率续期

    Args:
        ttl: 逻辑过期时间（秒）。物理 TTL 会额外加 60 秒以支持 stale-while-revalidate。
        key_prefix: 缓存键前缀
        tags: 标签列表，用于 Tag-Based Invalidation（如 ['user:123', 'model_configs']）
        beta: XFetch beta 参数，越大越倾向提前刷新（默认 1.0）
    """
    _tags = tags or []

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            cache_key = _stable_cache_key(key_prefix, func.__name__, args, kwargs)

            try:
                from app.utils.optimized_redis import get_async_redis_client
                redis_client = get_async_redis_client()

                # --- 读缓存 + XFetch 判断 ---
                raw = await redis_client.get(cache_key)
                if raw:
                    value, expire_at, compute_time = _unpack_xfetch_entry(raw)
                    now = time.time()
                    gap = max(compute_time, 0.01) * beta * math.log(random.random()) * -1
                    if now + gap < expire_at:
                        return value
                    # XFetch 触发：当前请求负责刷新（其他请求继续用旧值）
                    logger.debug(f"XFetch 触发刷新: {cache_key}")

                # --- Cache miss 或 XFetch 触发 → Singleflight ---
                async def _recompute():
                    start = time.time()
                    result = await func(*args, **kwargs)
                    elapsed = time.time() - start
                    packed = _pack_xfetch_entry(result, ttl, elapsed)
                    physical_ttl = ttl + 60
                    pipe = redis_client.pipeline()
                    pipe.setex(cache_key, physical_ttl, packed)
                    for tag in _tags:
                        tag_key = f"tag:{tag}"
                        pipe.sadd(tag_key, cache_key)
                        pipe.expire(tag_key, physical_ttl + 60)
                    await pipe.execute()
                    logger.debug(f"缓存写入: {cache_key}")
                    return result

                return await _singleflight.do(cache_key, _recompute)
            except Exception as e:
                logger.warning(f"缓存操作失败: {e}，直接执行函数")
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            cache_key = _stable_cache_key(key_prefix, func.__name__, args, kwargs)

            try:
                redis_pool = get_redis_pool()
                redis_client = redis.Redis(connection_pool=redis_pool)

                raw = redis_client.get(cache_key)
                if raw:
                    value, expire_at, compute_time = _unpack_xfetch_entry(raw)
                    now = time.time()
                    gap = max(compute_time, 0.01) * beta * math.log(random.random()) * -1
                    if now + gap < expire_at:
                        return value

                start = time.time()
                result = func(*args, **kwargs)
                elapsed = time.time() - start

                packed = _pack_xfetch_entry(result, ttl, elapsed)
                physical_ttl = ttl + 60
                pipe = redis_client.pipeline()
                pipe.setex(cache_key, physical_ttl, packed)
                for tag in _tags:
                    tag_key = f"tag:{tag}"
                    pipe.sadd(tag_key, cache_key)
                    pipe.expire(tag_key, physical_ttl + 60)
                pipe.execute()

                return result
            except Exception as e:
                logger.warning(f"缓存操作失败: {e}，直接执行函数")
                return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ---------------------------------------------------------------------------
# Tag-Based Invalidation（替代 KEYS 命令）
# ---------------------------------------------------------------------------
async def invalidate_by_tag(tag: str):
    """通过标签精确失效缓存（O(M)，M = 该标签下的 key 数量）。

    使用 UNLINK 替代 DEL —— 大 value 的内存回收在后台线程完成，不阻塞 Redis。
    """
    try:
        from app.utils.optimized_redis import get_async_redis_client
        redis_client = get_async_redis_client()
        tag_key = f"tag:{tag}"
        keys = await redis_client.smembers(tag_key)
        if keys:
            pipe = redis_client.pipeline()
            pipe.unlink(*keys)
            pipe.delete(tag_key)
            await pipe.execute()
            logger.info(f"Tag invalidation: tag={tag}, cleared {len(keys)} keys")
    except Exception as e:
        logger.error(f"Tag invalidation 失败: {e}")


def invalidate_by_tag_sync(tag: str):
    """同步版本的标签失效。"""
    try:
        redis_pool = get_redis_pool()
        rc = redis.Redis(connection_pool=redis_pool)
        tag_key = f"tag:{tag}"
        keys = rc.smembers(tag_key)
        if keys:
            pipe = rc.pipeline()
            pipe.unlink(*keys)
            pipe.delete(tag_key)
            pipe.execute()
            logger.info(f"Tag invalidation (sync): tag={tag}, cleared {len(keys)} keys")
    except Exception as e:
        logger.error(f"Tag invalidation (sync) 失败: {e}")


def clear_cache(key_pattern: str):
    """清除缓存 — 使用 SCAN 替代 KEYS，UNLINK 替代 DEL。

    仅用于管理/运维场景（如批量清理）。业务代码应使用 invalidate_by_tag。
    """
    try:
        redis_pool = get_redis_pool()
        redis_client = redis.Redis(connection_pool=redis_pool)

        deleted = 0
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match=key_pattern, count=200)
            if keys:
                redis_client.unlink(*keys)
                deleted += len(keys)
            if cursor == 0:
                break

        if deleted:
            logger.info(f"清除缓存: {deleted} 个键 (pattern={key_pattern})")
    except Exception as e:
        logger.error(f"清除缓存失败: {e}")
