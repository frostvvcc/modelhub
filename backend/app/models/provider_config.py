"""
供应商配置模型
管理 LLM 和 Embedding 模型的供应商配置（如 OpenAI、阿里云、Anthropic 等）
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Index, func, Enum as SQLEnum
from sqlalchemy.orm import relationship, backref
from app.extensions import Base
import enum

class ProviderType(enum.Enum):
    """供应商类型"""
    OPENAI = "openai"  # OpenAI
    ALIYUN = "aliyun"  # 阿里云
    ANTHROPIC = "anthropic"  # Anthropic
    LOCAL = "local"  # 本地模型
    CUSTOM = "custom"  # 自定义


class ProviderConfig(Base):
    """供应商配置模型"""
    __tablename__ = 'provider_config'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="供应商名称（如：OpenAI、阿里云通义千问）")
    code = Column(String(50), unique=True, nullable=False, comment="供应商代码（唯一，如：openai、aliyun）")
    provider_type = Column(String(50), nullable=False, comment="供应商类型：openai/aliyun/anthropic/local/custom")
    base_url = Column(String(500), nullable=False, comment="API 基础 URL")
    api_key = Column(String(500), nullable=True, comment="API Key（可选，某些供应商不需要）")
    api_secret = Column(String(500), nullable=True, comment="API Secret（可选）")
    config_json = Column(Text, nullable=True, comment="额外配置（JSON 格式）")
    description = Column(Text, nullable=True, comment="描述")
    is_active = Column(Boolean, default=True, nullable=False, comment="是否启用")
    is_default = Column(Boolean, default=False, nullable=False, comment="是否默认供应商")
    priority = Column(Integer, default=0, nullable=False, comment="优先级（数字越大优先级越高）")
    rate_limit = Column(Integer, nullable=True, comment="速率限制（每分钟请求数）")
    max_tokens = Column(Integer, nullable=True, comment="最大 token 数")
    supported_model_types = Column(String(100), nullable=True, comment="支持的模型类型（逗号分隔，如：chatllm,embedding）")
    create_at = Column(DateTime, server_default=func.now(), nullable=False)
    update_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )
    
    # 关系
    models = relationship('ModelInfo', back_populates='provider', lazy='dynamic')
    
    __table_args__ = (
        Index('idx_provider_code', code),
        Index('idx_provider_type', provider_type),
        Index('idx_provider_active', is_active),
        Index('idx_provider_default', is_default),
        Index('idx_provider_priority', priority),
    )
    
    def to_dict(self, include_sensitive=False):
        """转换为字典"""
        result = {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'provider_type': self.provider_type,
            'base_url': self.base_url,
            'description': self.description,
            'is_active': self.is_active,
            'is_default': self.is_default,
            'priority': self.priority,
            'rate_limit': self.rate_limit,
            'max_tokens': self.max_tokens,
            'supported_model_types': self.supported_model_types.split(',') if self.supported_model_types else [],
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }
        
        # 敏感信息只在需要时返回
        if include_sensitive:
            result['api_key'] = self.api_key
            result['api_secret'] = self.api_secret
            result['config_json'] = self.config_json
        
        return result
    
    def __repr__(self):
        return f"<ProviderConfig(id={self.id}, name='{self.name}', code='{self.code}')>"

