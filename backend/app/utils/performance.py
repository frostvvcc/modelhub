"""
性能监控和优化工具
提供性能统计和优化建议
"""
import time
import asyncio
import logging
from functools import wraps
from typing import Callable, TypeVar, Any
from contextlib import asynccontextmanager, contextmanager
from app.utils.logger_config import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


def async_timing(func: Callable) -> Callable:
    """异步函数执行时间统计装饰器"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.debug(f"{func.__name__} 执行时间: {elapsed:.3f}秒")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"{func.__name__} 执行失败 (耗时 {elapsed:.3f}秒): {e}")
            raise
    return wrapper


def sync_timing(func: Callable) -> Callable:
    """同步函数执行时间统计装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.debug(f"{func.__name__} 执行时间: {elapsed:.3f}秒")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"{func.__name__} 执行失败 (耗时 {elapsed:.3f}秒): {e}")
            raise
    return wrapper


@asynccontextmanager
async def async_timer(operation_name: str):
    """异步上下文管理器，用于计时"""
    start_time = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start_time
        logger.info(f"{operation_name} 耗时: {elapsed:.3f}秒")


@contextmanager
def sync_timer(operation_name: str):
    """同步上下文管理器，用于计时"""
    start_time = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start_time
        logger.info(f"{operation_name} 耗时: {elapsed:.3f}秒")


def measure_time(func: Callable) -> Callable:
    """
    通用的性能监控装饰器（支持同步和异步）
    """
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.debug(f"{func.__qualname__} 执行时间: {elapsed:.3f}秒")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.warning(f"{func.__qualname__} 执行失败 (耗时 {elapsed:.3f}秒): {e}")
            raise
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.debug(f"{func.__qualname__} 执行时间: {elapsed:.3f}秒")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.warning(f"{func.__qualname__} 执行失败 (耗时 {elapsed:.3f}秒): {e}")
            raise
    
    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper

