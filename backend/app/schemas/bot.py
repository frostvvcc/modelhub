"""
Bot Pydantic schemas
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class BotCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    avatar: Optional[str] = None
    system_prompt: Optional[str] = None
    greeting: Optional[str] = Field(None, max_length=500)
    forbidden_topics: Optional[List[str]] = []
    model_config_id: Optional[int] = None
    vector_db_ids: Optional[List[int]] = []
    organization_id: Optional[int] = None


class BotUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    avatar: Optional[str] = None
    system_prompt: Optional[str] = None
    greeting: Optional[str] = Field(None, max_length=500)
    forbidden_topics: Optional[List[str]] = None
    model_config_id: Optional[int] = None
    vector_db_ids: Optional[List[int]] = None
    organization_id: Optional[int] = None


class BotResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    avatar: Optional[str]
    system_prompt: Optional[str]
    greeting: Optional[str]
    forbidden_topics: List[str] = []
    model_config_id: Optional[int]
    vector_db_ids: List[int] = []
    organization_id: Optional[int] = None
    org_name: Optional[str] = None
    user_id: int
    creator_name: Optional[str] = None
    created_at: Optional[str]
    updated_at: Optional[str]

    class Config:
        from_attributes = True


class BotChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: Optional[str] = None


class BotChatResponse(BaseModel):
    answer: str
    conversation_id: Optional[str]
    forbidden_topic_hit: Optional[str] = None
    model_name: Optional[str] = None
    rag_info: Optional[Dict[str, Any]] = None
    sources: Optional[List[Dict[str, Any]]] = None
    grounded_ratio: Optional[float] = None
    grounded_level: Optional[str] = None
