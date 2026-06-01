"""
对话相关数据模型
"""
from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    """对话请求"""
    conversation_id: Optional[int] = None
    model_config_id: Optional[int] = None
    message: str


class ChatHistoryRequest(BaseModel):
    """获取对话历史请求"""
    conversation_id: int

