import decimal
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Numeric, ForeignKey, Index, func
from sqlalchemy.orm import relationship, backref
from app.extensions import Base


class ModelConfig(Base):
    __tablename__ = 'model_config'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    share_id = Column(String(255), unique=True, nullable=False)
    base_model_id = Column(Integer, ForeignKey('model_info.id'), nullable=False)
    name = Column(String(255), nullable=False)
    temperature = Column(Numeric(10, 2), default=decimal.Decimal('0.70'), nullable=False)
    top_p = Column(Numeric(10, 2), default=decimal.Decimal('0.70'), nullable=False)
    prompt = Column(Text, nullable=True)
    prompt_variables = Column(Text, nullable=True, comment="Prompt 模板变量 JSON")
    knowledge_context_template = Column(Text, nullable=True, comment="知识库上下文模板")
    citation_template = Column(String(100), nullable=True, default="[来源{index}]", comment="引用格式模板")
    refusal_strategy = Column(Text, nullable=True, comment="资料不足或禁止回答时的策略")
    max_context_chars = Column(Integer, nullable=False, default=6000, comment="注入模型的最大知识库上下文字符数")
    answer_with_citations = Column(Boolean, default=True, nullable=False, comment="回答正文是否要求插入来源编号")
    describe = Column(String(255), nullable=True)
    organization_id = Column(Integer, ForeignKey('organization.id'), nullable=True, comment="归属组织ID：NULL=私有，学校ID=全校可见，学院ID=学院可见")
    create_at = Column(DateTime, server_default=func.now(), nullable=False)
    update_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )

    user = relationship('User', backref=backref('model_configs', lazy=True))
    base_model = relationship('ModelInfo', backref=backref('model_configs', lazy=True))
    organization = relationship('Organization', foreign_keys=[organization_id], backref=backref('model_configs', lazy='dynamic'))
    __table_args__ = (
        Index('idx_model_config_base_model_id', base_model_id),
        Index('idx_model_config_user_id', user_id),
        Index('idx_model_config_organization_id', organization_id),
    )

    def to_dict(self):
        create_at_str = self.create_at.strftime('%Y-%m-%d %H:%M:%S') if self.create_at else None
        update_at_str = self.update_at.strftime('%Y-%m-%d %H:%M:%S') if self.update_at else None
        return {
            'id': self.id,
            'user_id': self.user_id,
            'share_id': self.share_id,
            'base_model_id': self.base_model_id,
            'name': self.name,
            'temperature': float(self.temperature),
            'top_p': float(self.top_p),
            'prompt': self.prompt,
            'prompt_variables': self.prompt_variables,
            'knowledge_context_template': self.knowledge_context_template,
            'citation_template': self.citation_template,
            'refusal_strategy': self.refusal_strategy,
            'max_context_chars': self.max_context_chars,
            'answer_with_citations': self.answer_with_citations,
            'describe': self.describe,
            'organization_id': self.organization_id,
            'org_name': self.organization.name if self.organization else None,
            'create_at': create_at_str,
            'update_at': update_at_str,
        }
