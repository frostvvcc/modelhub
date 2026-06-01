"""
模型相关数据模型
"""
from pydantic import BaseModel, Field
from typing import Optional


class ModelConfigCreate(BaseModel):
    """创建模型配置请求"""
    share_id: str
    base_model_id: int
    name: str
    temperature: float = Field(ge=0.0, le=2.0, description="温度参数，控制随机性")
    top_p: float = Field(ge=0.0, le=1.0, description="Top-p 参数，控制多样性")
    prompt: Optional[str] = None
    prompt_variables: Optional[str] = Field(default=None, description="Prompt 模板变量 JSON")
    knowledge_context_template: Optional[str] = Field(default=None, description="知识库上下文模板")
    citation_template: Optional[str] = Field(default="[来源{index}]", description="引用格式模板")
    refusal_strategy: Optional[str] = Field(default=None, description="资料不足或禁止回答策略")
    max_context_chars: int = Field(default=6000, ge=1000, le=30000, description="最大知识库上下文字符数")
    answer_with_citations: bool = Field(default=True, description="回答正文是否插入来源编号")
    describe: Optional[str] = None
    organization_id: Optional[int] = Field(default=None, description="归属组织ID：NULL=私有，学校ID=全校可见，学院ID=学院可见")


class ModelConfigUpdate(BaseModel):
    """更新模型配置请求"""
    id: int
    share_id: Optional[str] = None
    base_model_id: Optional[int] = None
    name: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    prompt: Optional[str] = None
    prompt_variables: Optional[str] = None
    knowledge_context_template: Optional[str] = None
    citation_template: Optional[str] = None
    refusal_strategy: Optional[str] = None
    max_context_chars: Optional[int] = Field(None, ge=1000, le=30000)
    answer_with_citations: Optional[bool] = None
    describe: Optional[str] = None
    organization_id: Optional[int] = None
