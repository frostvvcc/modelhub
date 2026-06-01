from sqlalchemy import Column, Integer, String, DateTime, Enum, func, ForeignKey, Index, Text, Boolean
from sqlalchemy.orm import relationship, backref
from app.extensions import Base


class ModelInfo(Base):
    """模型信息模型（关联供应商配置）"""
    __tablename__ = 'model_info'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String(255), unique=True, nullable=False, comment="模型名称（如：gpt-4、qwen-turbo）")
    type = Column(Enum('chatllm', 'embedding'), nullable=False, comment="模型类型：chatllm/embedding")
    provider_id = Column(Integer, ForeignKey('provider_config.id'), nullable=False, comment="供应商配置ID")
    # 保留 base_url 和 api_key 字段用于向后兼容，但优先使用 provider 配置
    base_url = Column(String(500), nullable=True, comment="API 基础 URL（可选，优先使用 provider 配置）")
    api_key = Column(String(500), nullable=True, comment="API Key（可选，优先使用 provider 配置）")
    model_endpoint = Column(String(255), nullable=True, comment="模型端点路径（如：/v1/chat/completions）")
    describe = Column(Text, nullable=True, comment="模型描述")
    version = Column(String(50), nullable=True, comment="模型版本")
    max_tokens = Column(Integer, nullable=True, comment="最大 token 数")
    context_window = Column(Integer, nullable=True, comment="上下文窗口大小")
    is_active = Column(Boolean, default=True, nullable=False, comment="是否启用")
    is_default = Column(Boolean, default=False, nullable=False, comment="是否默认模型")
    priority = Column(Integer, default=0, nullable=False, comment="优先级")
    create_at = Column(DateTime, server_default=func.now(), nullable=False)
    update_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )
    
    # 关系
    provider = relationship('ProviderConfig', back_populates='models')
    
    __table_args__ = (
        Index('idx_model_name', model_name),
        Index('idx_model_type', type),
        Index('idx_model_provider_id', provider_id),
        Index('idx_model_active', is_active),
        Index('idx_model_default', is_default),
    )
    
    def get_base_url(self):
        """获取基础 URL（优先使用 provider 配置）"""
        # 检查 provider 是否已加载且有 base_url
        if hasattr(self, 'provider') and self.provider:
            # 使用 inspect 检查关系是否已加载
            from sqlalchemy import inspect
            insp = inspect(self)
            if 'provider' in insp.unloaded:
                # provider 未加载，返回本地配置
                return self.base_url
            # provider 已加载，使用 provider 的配置
            if self.provider.base_url:
                return self.provider.base_url
        return self.base_url

    def get_api_key(self):
        """获取 API Key（优先使用 provider 配置）"""
        # 检查 provider 是否已加载且有 api_key
        if hasattr(self, 'provider') and self.provider:
            # 使用 inspect 检查关系是否已加载
            from sqlalchemy import inspect
            insp = inspect(self)
            if 'provider' in insp.unloaded:
                # provider 未加载，返回本地配置
                return self.api_key
            # provider 已加载，使用 provider 的配置
            if self.provider.api_key:
                return self.provider.api_key
        return self.api_key
    
    def to_dict(self, include_sensitive=False):
        """转换为字典"""
        result = {
            'id': self.id,
            'model_name': self.model_name,
            'type': self.type,
            'provider_id': self.provider_id,
            'provider_name': self.provider.name if self.provider else None,
            'provider_code': self.provider.code if self.provider else None,
            'model_endpoint': self.model_endpoint,
            'describe': self.describe,
            'version': self.version,
            'max_tokens': self.max_tokens,
            'context_window': self.context_window,
            'is_active': self.is_active,
            'is_default': self.is_default,
            'priority': self.priority,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }
        
        # 敏感信息只在需要时返回
        if include_sensitive:
            result['base_url'] = self.get_base_url()
            result['api_key'] = self.get_api_key()
        
        return result
    
    def __repr__(self):
        return f"<ModelInfo(id={self.id}, model_name='{self.model_name}', type='{self.type}')>"
