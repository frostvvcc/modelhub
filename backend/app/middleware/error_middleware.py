"""
错误处理中间件
统一处理应用异常
"""
import asyncio

from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError, OperationalError, DataError
from app.utils.error_handler import AppException, InternalServerError, ValidationError
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


async def error_handler_middleware(request: Request, call_next):
    """
    错误处理中间件
    统一处理所有异常，转换为标准响应格式
    """
    try:
        response = await call_next(request)
        return response
    except asyncio.CancelledError:
        raise
    except RequestValidationError as e:
        errors = e.errors()
        error_details = []
        for error in errors:
            loc = " -> ".join(str(x) for x in error.get("loc", []))
            msg = error.get("msg", "")
            error_type = error.get("type", "")
            error_details.append(f"[{loc}] {msg} (type: {error_type})")
            logger.error(f"[调试-422错误] 位置: {loc}, 消息: {msg}, 类型: {error_type}")

        logger.error(
            f"[调试-422错误] 请求验证失败 [{request.method} {request.url.path}]: {error_details}"
        )

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "message": f"请求参数验证失败: {'; '.join(error_details)}",
                "code": 422,
                "details": errors
            }
        )
    except AppException as e:
        logger.warning(
            f"应用异常 [{request.method} {request.url.path}]: {e.message} (code: {e.code})"
        )

        status_code_map = {
            400: status.HTTP_400_BAD_REQUEST,
            401: status.HTTP_401_UNAUTHORIZED,
            403: status.HTTP_403_FORBIDDEN,
            404: status.HTTP_404_NOT_FOUND,
            409: status.HTTP_409_CONFLICT,
            500: status.HTTP_500_INTERNAL_SERVER_ERROR,
        }

        http_status = status_code_map.get(e.code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        return JSONResponse(
            status_code=http_status,
            content={
                "success": False,
                "message": e.message,
                "code": e.code,
                "details": e.details
            }
        )
    except IntegrityError as e:
        logger.warning(
            f"数据库约束冲突 [{request.method} {request.url.path}]: {e.orig}",
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "success": False,
                "message": "数据冲突：违反唯一约束或外键约束",
                "code": 409,
                "details": None
            }
        )
    except OperationalError as e:
        logger.error(
            f"数据库连接异常 [{request.method} {request.url.path}]: {e.orig}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "success": False,
                "message": "数据库服务暂时不可用，请稍后重试",
                "code": 503,
                "details": None
            }
        )
    except DataError as e:
        logger.warning(
            f"数据库数据格式错误 [{request.method} {request.url.path}]: {e.orig}",
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "success": False,
                "message": "请求数据格式不正确",
                "code": 400,
                "details": None
            }
        )
    except Exception as e:
        logger.error(
            f"未处理的异常 [{request.method} {request.url.path}]: {str(e)}",
            exc_info=True
        )

        app_exception = InternalServerError(f"服务器内部错误: {str(e)}")

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": app_exception.message,
                "code": app_exception.code,
                "details": app_exception.details
            }
        )
