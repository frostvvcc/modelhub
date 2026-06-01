"""
响应模型
"""
from typing import Generic, TypeVar, Optional, Any
from pydantic import BaseModel

T = TypeVar('T')


class BaseResponse(BaseModel, Generic[T]):
    """基础响应模型"""
    message: str = "success"
    data: Optional[T] = None


class SuccessResponse(BaseResponse[T]):
    """成功响应"""
    message: str = "success"
    data: Optional[T] = None


class ErrorResponse(BaseModel):
    """错误响应"""
    message: str
    data: Optional[Any] = None
    code: Optional[int] = None

