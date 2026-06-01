"""
缓存工具
使用 Redis 实现缓存装饰器
"""
from functools import wraps
import json
import hashlib
from typing import Callable, Any
import logging
from app.config import settings
from app.utils.optimized_redis import get_redis_pool
import redis

logger = logging.getLogger(__name__)


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
            # 生成缓存键
            cache_key = f"{key_prefix}:{func.__name__}:{hashlib.md5(str(args + tuple(kwargs.items())).encode()).hexdigest()}"
            
            try:
                redis_pool = get_redis_pool()
                redis_client = redis.Redis(connection_pool=redis_pool)
                
                # 从 Redis 获取
                cached = redis_client.get(cache_key)
                if cached:
                    logger.debug(f"缓存命中: {cache_key}")
                    return json.loads(cached)
                
                # 执行函数
                result = await func(*args, **kwargs)
                
                # 缓存结果
                redis_client.setex(cache_key, ttl, json.dumps(result, default=str))
                logger.debug(f"缓存写入: {cache_key}")
                
                return result
            except Exception as e:
                logger.warning(f"缓存操作失败: {e}，直接执行函数")
                return await func(*args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # 同步函数版本
            cache_key = f"{key_prefix}:{func.__name__}:{hashlib.md5(str(args + tuple(kwargs.items())).encode()).hexdigest()}"
            
            try:
                redis_pool = get_redis_pool()
                redis_client = redis.Redis(connection_pool=redis_pool)
                
                cached = redis_client.get(cache_key)
                if cached:
                    logger.debug(f"缓存命中: {cache_key}")
                    return json.loads(cached)
                
                result = func(*args, **kwargs)
                
                redis_client.setex(cache_key, ttl, json.dumps(result, default=str))
                logger.debug(f"缓存写入: {cache_key}")
                
                return result
            except Exception as e:
                logger.warning(f"缓存操作失败: {e}，直接执行函数")
                return func(*args, **kwargs)
        
        # 根据函数类型返回对应的包装器
        if hasattr(func, '__code__') and 'async' in str(func.__code__.co_flags):
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

