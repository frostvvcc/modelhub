"""
服务层装饰器
提供统一的异常处理、日志记录和性能监控
"""
from functools import wraps
from typing import Callable, Any
from app.utils.logger_config import get_logger
from app.utils.error_handler import (
    AppException, 
    InternalServerError
)
from app.utils.performance import measure_time

logger = get_logger(__name__)


def log_service_call(func: Callable) -> Callable:
    """
    服务方法调用日志装饰器
    记录方法调用、参数和结果
    """
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        func_name = f"{func.__module__}.{func.__qualname__}"
        logger.info(f"调用服务方法: {func_name}")
        
        # 记录参数（排除敏感信息）
        safe_kwargs = {k: v for k, v in kwargs.items() 
                       if k not in ['password', 'token', 'api_key']}
        if safe_kwargs:
            logger.debug(f"参数: {safe_kwargs}")
        
        try:
            result = await func(*args, **kwargs)
            logger.info(f"服务方法执行成功: {func_name}")
            return result
        except Exception as e:
            logger.error(f"服务方法执行失败: {func_name} - {str(e)}", exc_info=True)
            raise
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        func_name = f"{func.__module__}.{func.__qualname__}"
        logger.info(f"调用服务方法: {func_name}")
        
        safe_kwargs = {k: v for k, v in kwargs.items() 
                       if k not in ['password', 'token', 'api_key']}
        if safe_kwargs:
            logger.debug(f"参数: {safe_kwargs}")
        
        try:
            result = func(*args, **kwargs)
            logger.info(f"服务方法执行成功: {func_name}")
            return result
        except Exception as e:
            logger.error(f"服务方法执行失败: {func_name} - {str(e)}", exc_info=True)
            raise
    
    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


def handle_exceptions(func: Callable) -> Callable:
    """
    异常处理装饰器
    自动处理异常并转换为标准异常
    """
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except AppException:
            # 标准异常，直接抛出
            raise
        except Exception as e:
            # 未知异常转换为内部服务器错误
            logger.error(f"未处理的异常 [{func.__name__}]: {e}", exc_info=True)
            raise InternalServerError(f"未处理的异常: {str(e)}")
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AppException:
            raise
        except Exception as e:
            logger.error(f"未处理的异常 [{func.__name__}]: {e}", exc_info=True)
            raise InternalServerError(f"未处理的异常: {str(e)}")
    
    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


def service_method(func: Callable) -> Callable:
    """
    服务方法装饰器（组合装饰器）
    包含：日志记录、异常处理、性能监控
    
    使用方式:
        @service_method
        async def my_service_method(...):
            ...
    """
    # 先应用 measure_time
    timed_func = measure_time(func)
    
    # 再应用 handle_exceptions
    exception_handled_func = handle_exceptions(timed_func)
    
    # 最后应用 log_service_call
    return log_service_call(exception_handled_func)

