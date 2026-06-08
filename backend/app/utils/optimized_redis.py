"""
优化的Redis连接池实现
使用连接池管理Redis连接，提升性能和稳定性
"""
import redis
from redis.connection import ConnectionPool
from typing import Optional
import logging
import os

logger = logging.getLogger(__name__)

# 全局连接池
_redis_pool: Optional[ConnectionPool] = None
_pool_lock = __import__('threading').Lock()


class NoOpRedisClient:
    """Redis 不可用时的空实现，保留数据库作为真实存储。"""

    def ping(self) -> bool:
        return False

    def rpush(self, *args, **kwargs) -> int:
        return 0

    def delete(self, *args, **kwargs) -> int:
        return 0


def get_redis_pool() -> ConnectionPool:
    """获取或创建Redis连接池"""
    global _redis_pool
    if _redis_pool is None:
        with _pool_lock:
            if _redis_pool is None:
                _redis_pool = ConnectionPool(
                    host=os.getenv("REDIS_HOST", "127.0.0.1"),
                    port=int(os.getenv("REDIS_PORT", "6379")),
                    db=int(os.getenv("REDIS_DB", "0")),
                    password=os.getenv("REDIS_PASSWORD", None),
                    max_connections=50,
                    decode_responses=True,
                    retry_on_timeout=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    health_check_interval=30
                )
                logger.info("Redis连接池已创建")
    return _redis_pool


class OptimizedConversationStore:
    """优化的对话存储，使用连接池"""
    
    def __init__(self):
        self._pool = get_redis_pool()
        self._client = None
    
    @property
    def redis_client(self):
        """获取Redis客户端（延迟初始化）"""
        if self._client is None:
            try:
                self._client = redis.Redis(connection_pool=self._pool)
                # 测试连接
                self._client.ping()
                logger.info("Redis 客户端初始化成功")
            except Exception as e:
                logger.warning(f"Redis 连接失败，将使用数据库存储: {e}")
                self._client = NoOpRedisClient()
        return self._client
    
    def health_check(self) -> bool:
        """健康检查"""
        try:
            return self.redis_client.ping()
        except Exception as e:
            logger.error(f"Redis健康检查失败: {e}")
            return False


# 异步 Redis 客户端（供 async 代码路径使用，避免阻塞事件循环）
_async_redis_client = None
_async_lock = __import__('asyncio').Lock() if hasattr(__import__('asyncio'), 'Lock') else None


def get_async_redis_client():
    """获取异步 Redis 客户端（懒初始化，非协程版本，线程安全）"""
    global _async_redis_client
    if _async_redis_client is None:
        try:
            import redis.asyncio as aioredis
            _async_redis_client = aioredis.Redis(
                host=os.getenv("REDIS_HOST", "127.0.0.1"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                db=int(os.getenv("REDIS_DB", "0")),
                password=os.getenv("REDIS_PASSWORD", None),
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            logger.info("异步 Redis 客户端已创建")
        except ImportError:
            logger.warning("redis.asyncio 不可用，异步缓存将降级为同步调用")
            pool = get_redis_pool()
            _async_redis_client = redis.Redis(connection_pool=pool)
    return _async_redis_client
