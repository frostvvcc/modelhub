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
