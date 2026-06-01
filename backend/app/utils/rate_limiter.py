"""
API 限流工具
"""
from functools import wraps
from typing import Callable
from fastapi import Request, HTTPException, status
import redis
import logging
from app.config import settings
from app.utils.optimized_redis import get_redis_pool

logger = logging.getLogger(__name__)


def rate_limit(requests_per_minute: int = 60):
    """
    API 限流装饰器
    
    Args:
        requests_per_minute: 每分钟允许的请求数
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            if not settings.rate_limit_enabled:
                return await func(request, *args, **kwargs)
            
            # 获取客户端标识（IP 或用户 ID）
            client_id = request.client.host if request.client else "unknown"
            
            # 如果有用户认证，使用用户 ID
            if hasattr(request.state, 'user'):
                client_id = f"user_{request.state.user.id}"
            
            # 生成限流键
            rate_limit_key = f"rate_limit:{func.__name__}:{client_id}"
            
            try:
                redis_pool = get_redis_pool()
                redis_client = redis.Redis(connection_pool=redis_pool)
                
                # 使用滑动窗口算法
                current = redis_client.incr(rate_limit_key)
                if current == 1:
                    redis_client.expire(rate_limit_key, 60)  # 设置过期时间
                
                if current > requests_per_minute:
                    logger.warning(f"限流触发: {client_id} 超过 {requests_per_minute} 次/分钟")
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"请求过于频繁，请稍后再试。限制: {requests_per_minute} 次/分钟"
                    )
                
                return await func(request, *args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"限流检查失败: {e}，允许请求通过")
                return await func(request, *args, **kwargs)
        
        return wrapper
    
    return decorator

