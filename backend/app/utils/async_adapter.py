"""
异步适配器
将同步的 Service 和 Mapper 调用包装为异步
"""
import asyncio
from functools import wraps
from typing import Callable, Any
import logging

logger = logging.getLogger(__name__)


def async_wrapper(func: Callable) -> Callable:
    """
    将同步函数包装为异步函数
    
    用法:
        @async_wrapper
        def sync_function():
            ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 使用线程池执行同步函数
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
    
    return wrapper


def to_async(func: Callable) -> Callable:
    """
    将同步函数转换为异步函数（使用 asyncio.to_thread，Python 3.9+）
    
    用法:
        async_result = await to_async(sync_function)(arg1, arg2)
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            # Python 3.9+ 使用 asyncio.to_thread
            return await asyncio.to_thread(func, *args, **kwargs)
        except AttributeError:
            # Python < 3.9 使用 run_in_executor
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
    
    return wrapper


class AsyncService:
    """
    异步 Service 包装器
    将同步的 Service 方法包装为异步
    """
    
    @staticmethod
    async def run_sync(func: Callable, *args, **kwargs) -> Any:
        """
        异步执行同步函数
        
        Args:
            func: 要执行的同步函数
            *args: 位置参数
            **kwargs: 关键字参数
        
        Returns:
            函数执行结果
        """
        try:
            # Python 3.9+ 使用 asyncio.to_thread
            return await asyncio.to_thread(func, *args, **kwargs)
        except AttributeError:
            # Python < 3.9 使用 run_in_executor
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
    
    @staticmethod
    async def run_sync_many(funcs: list[tuple[Callable, tuple, dict]]) -> list[Any]:
        """
        并发执行多个同步函数
        
        Args:
            funcs: 函数列表，每个元素是 (func, args, kwargs) 元组
        
        Returns:
            结果列表
        """
        tasks = [
            AsyncService.run_sync(func, *args, **kwargs)
            for func, args, kwargs in funcs
        ]
        return await asyncio.gather(*tasks)

