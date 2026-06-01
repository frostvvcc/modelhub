"""
统一错误处理工具
提供标准化的错误响应和异常处理
"""
from typing import Optional, Dict, Any, Callable
from functools import wraps
from fastapi import HTTPException, status
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


class AppException(Exception):
    """应用基础异常类"""
    def __init__(
        self,
        message: str,
        code: int = 500,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(AppException):
    """验证错误"""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=400, details=details)


class NotFoundError(AppException):
    """资源未找到错误"""
    def __init__(self, message: str = "资源不存在", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=404, details=details)


class UnauthorizedError(AppException):
    """未授权错误"""
    def __init__(self, message: str = "未授权", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=401, details=details)


class ForbiddenError(AppException):
    """禁止访问错误"""
    def __init__(self, message: str = "禁止访问", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=403, details=details)


class ConflictError(AppException):
    """资源冲突错误（如重复创建）"""
    def __init__(self, message: str = "资源已存在", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=409, details=details)


class BadRequestError(AppException):
    """请求错误"""
    def __init__(self, message: str = "请求参数错误", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=400, details=details)


class InternalServerError(AppException):
    """服务器内部错误"""
    def __init__(self, message: str = "服务器内部错误", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=500, details=details)


def handle_app_exception(e: AppException) -> HTTPException:
    """将应用异常转换为 HTTP 异常"""
    status_code_map = {
        400: status.HTTP_400_BAD_REQUEST,
        401: status.HTTP_401_UNAUTHORIZED,
        403: status.HTTP_403_FORBIDDEN,
        404: status.HTTP_404_NOT_FOUND,
        500: status.HTTP_500_INTERNAL_SERVER_ERROR,
    }
    
    http_status = status_code_map.get(e.code, status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    return HTTPException(
        status_code=http_status,
        detail={
            "message": e.message,
            "code": e.code,
            "details": e.details
        }
    )


def handle_exception(e: Exception, default_message: str = "服务器内部错误") -> HTTPException:
    """处理通用异常"""
    logger.exception(f"未处理的异常: {e}")
    
    if isinstance(e, AppException):
        return handle_app_exception(e)
    
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "message": default_message,
            "code": 500,
            "error": str(e)
        }
    )


def handle_service_exception(func: Callable) -> Callable:
    """
    服务层异常处理装饰器
    自动处理和记录异常
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
            logger.error(f"服务层异常 [{func.__name__}]: {e}", exc_info=True)
            raise InternalServerError(f"未处理的异常: {str(e)}")
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AppException:
            raise
        except Exception as e:
            logger.error(f"服务层异常 [{func.__name__}]: {e}", exc_info=True)
            raise InternalServerError(f"未处理的异常: {str(e)}")
    
    # 检查是否是协程函数
    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper

