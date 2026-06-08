"""
缓存工具
使用 Redis 实现缓存装饰器

缓存键生成：SHA256 + JSON 确定性序列化（sort_keys），避免 MD5 碰撞和参数顺序不稳定问题。
支持缓存版本号，数据结构变更时递增 version 即可批量失效旧缓存。
"""
from functools import wraps
import json
import hashlib
import asyncio
import inspect
from typing import Callable, Any
import logging
from app.config import settings
from app.utils.optimized_redis import get_redis_pool
import redis

logger = logging.getLogger(__name__)

_CACHE_VERSION = 1


def _stable_cache_key(prefix: str, func_name: str, args: tuple, kwargs: dict) -> str:
    """生成确定性缓存键：SHA256 + JSON 稳定序列化"""
    key_data = json.dumps(
        {"a": list(args), "k": kwargs},
        sort_keys=True,
        default=str,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(key_data.encode("utf-8")).hexdigest()[:20]
    return f"v{_CACHE_VERSION}:{prefix}:{func_name}:{digest}"


def cache_result(ttl: int = 3600, key_prefix: str = ""):
    """
    缓存装饰器

    Args:
        ttl: 缓存过期时间（秒）
        key_prefix: 缓存键前缀
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            cache_key = _stable_cache_key(key_prefix, func.__name__, args, kwargs)

            try:
                from app.utils.optimized_redis import get_async_redis_client
                redis_client = get_async_redis_client()

                cached = await redis_client.get(cache_key)
                if cached:
                    logger.debug(f"缓存命中: {cache_key}")
                    return json.loads(cached)

                result = await func(*args, **kwargs)

                await redis_client.setex(cache_key, ttl, json.dumps(result, default=str, ensure_ascii=False))
                logger.debug(f"缓存写入: {cache_key}")

                return result
            except Exception as e:
                logger.warning(f"缓存操作失败: {e}，直接执行函数")
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            cache_key = _stable_cache_key(key_prefix, func.__name__, args, kwargs)

            try:
                redis_pool = get_redis_pool()
                redis_client = redis.Redis(connection_pool=redis_pool)

                cached = redis_client.get(cache_key)
                if cached:
                    logger.debug(f"缓存命中: {cache_key}")
                    return json.loads(cached)

                result = func(*args, **kwargs)

                redis_client.setex(cache_key, ttl, json.dumps(result, default=str, ensure_ascii=False))
                logger.debug(f"缓存写入: {cache_key}")

                return result
            except Exception as e:
                logger.warning(f"缓存操作失败: {e}，直接执行函数")
                return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def clear_cache(key_pattern: str):
    """
    清除缓存
    
    Args:
        key_pattern: 缓存键模式（支持通配符）
    """
    try:
        redis_pool = get_redis_pool()
        redis_client = redis.Redis(connection_pool=redis_pool)
        
        # 查找匹配的键
        keys = redis_client.keys(key_pattern)
        if keys:
            redis_client.delete(*keys)
            logger.info(f"清除缓存: {len(keys)} 个键")
    except Exception as e:
        logger.error(f"清除缓存失败: {e}")

