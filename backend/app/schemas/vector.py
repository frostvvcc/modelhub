"""
向量数据库相关数据模型
"""
from pydantic import BaseModel, Field
from typing import Optional


class VectorDbCreate(BaseModel):
    """创建向量数据库请求"""
    name: str
    embedding_id: int
    describe: Optional[str] = None
    document_similarity: float = Field(default=0.7, ge=0.0, le=1.0)
    organization_id: Optional[int] = None


class VectorDbUpdate(BaseModel):
    """更新向量数据库请求"""
    name: Optional[str] = None
    embedding_id: Optional[int] = None
    describe: Optional[str] = None
    document_similarity: Optional[float] = Field(None, ge=0.0, le=1.0)
    organization_id: Optional[int] = None


class VectorQueryRequest(BaseModel):
    """向量查询请求"""
    query_text: str
    n_results: int = Field(default=10, ge=1, le=100)


class VectorQueryWithHierarchyRequest(BaseModel):
    """层级向量查询请求"""
    query_text: str
    n_results: int = Field(default=10, ge=1, le=100)
    folder_path: Optional[str] = None
    parent_id: Optional[int] = None
