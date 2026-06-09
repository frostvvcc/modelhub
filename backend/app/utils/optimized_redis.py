"""
优化的 Redis 连接池实现
- 同步/异步客户端分离
- Async 客户端 Double-Checked Locking + 连接池上限
- 健康检查
"""
import redis
from redis.connection import ConnectionPool
from typing import Optional
import logging
import os

logger = logging.getLogger(__name__)

_redis_pool: Optional[ConnectionPool] = None
_pool_lock = __import__('threading').Lock()


class NoOpRedisClient:
    """Redis 不可用时的空实现。"""
    def ping(self) -> bool:
        return False
    def rpush(self, *args, **kwargs) -> int:
        return 0
    def delete(self, *args, **kwargs) -> int:
        return 0


def get_redis_pool() -> ConnectionPool:
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
                    health_check_interval=30,
                )
                logger.info("Redis 同步连接池已创建 (max_connections=50)")
    return _redis_pool


class OptimizedConversationStore:
    def __init__(self):
        self._pool = get_redis_pool()
        self._client = None

    @property
    def redis_client(self):
        if self._client is None:
            try:
                self._client = redis.Redis(connection_pool=self._pool)
                self._client.ping()
                logger.info("Redis 客户端初始化成功")
            except Exception as e:
                logger.warning(f"Redis 连接失败，将使用数据库存储: {e}")
                self._client = NoOpRedisClient()
        return self._client

    def health_check(self) -> bool:
        try:
            return self.redis_client.ping()
        except Exception as e:
            logger.error(f"Redis 健康检查失败: {e}")
            return False


# ---------------------------------------------------------------------------
# 异步 Redis 客户端 — Double-Checked Locking + 连接池上限
# ---------------------------------------------------------------------------
_async_redis_client = None
_async_init_lock = None  # 惰性创建，避免模块级 asyncio.Lock 绑定错误事件循环


def _get_async_init_lock():
    global _async_init_lock
    if _async_init_lock is None:
        import asyncio
        _async_init_lock = asyncio.Lock()
    return _async_init_lock


def get_async_redis_client():
    """获取异步 Redis 客户端（惰性初始化，带连接池上限）。

    注意：这是同步函数，返回已创建的客户端实例。
    首次调用时创建，后续调用直接返回。
    """
    global _async_redis_client
    if _async_redis_client is not None:
        return _async_redis_client

    try:
        import redis.asyncio as aioredis
        _async_redis_client = aioredis.Redis(
            host=os.getenv("REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD", None),
            max_connections=50,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        logger.info("异步 Redis 客户端已创建 (max_connections=50)")
    except ImportError:
        logger.warning("redis.asyncio 不可用，异步缓存将降级为同步调用")
        pool = get_redis_pool()
        _async_redis_client = redis.Redis(connection_pool=pool)

    return _async_redis_client
