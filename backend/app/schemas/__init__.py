"""
Pydantic 数据模型
"""
from app.schemas.response import SuccessResponse, ErrorResponse
from app.schemas.user import RegisterRequest, LoginRequest, UserInfoResponse, TokenResponse
from app.schemas.model import ModelConfigCreate, ModelConfigUpdate
from app.schemas.vector import VectorDbCreate, VectorDbUpdate, VectorQueryRequest
from app.schemas.chat import ChatRequest, ChatHistoryRequest

__all__ = [
    "SuccessResponse",
    "ErrorResponse",
    "RegisterRequest",
    "LoginRequest",
    "UserInfoResponse",
    "TokenResponse",
    "ModelConfigCreate",
    "ModelConfigUpdate",
    "VectorDbCreate",
    "VectorDbUpdate",
    "VectorQueryRequest",
    "ChatRequest",
    "ChatHistoryRequest",
]

