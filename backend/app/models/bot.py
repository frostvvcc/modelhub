"""
Bot（数字助理）数据模型
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Index, func
from sqlalchemy.orm import relationship, backref
from app.extensions import Base


class Bot(Base):
    __tablename__ = 'bot'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, comment="Bot 名称")
    description = Column(Text, nullable=True, comment="Bot 描述")
    avatar = Column(String(255), nullable=True, comment="Bot 头像 URL")
    system_prompt = Column(Text, nullable=True, comment="系统提示词（人设/角色设定）")
    greeting = Column(String(500), nullable=True, comment="开场白")
    forbidden_topics = Column(JSON, nullable=True, comment="禁止话题列表")
    model_config_id = Column(Integer, ForeignKey('model_config.id'), nullable=True, comment="关联模型配置")
    vector_db_ids = Column(JSON, nullable=True, comment="关联知识库 ID 列表")
    organization_id = Column(
        Integer, ForeignKey('organization.id'), nullable=True,
        comment="归属组织ID：NULL=私有，学校ID=全校可见，学院ID=学院可见"
    )
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False, comment="创建者")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )

    user = relationship('User', backref=backref('bots', lazy='dynamic'))
    organization = relationship('Organization', foreign_keys=[organization_id], backref=backref('bots', lazy='dynamic'))

    __table_args__ = (
        Index('idx_bot_user_id', user_id),
        Index('idx_bot_organization_id', organization_id),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'avatar': self.avatar,
            'system_prompt': self.system_prompt,
            'greeting': self.greeting,
            'forbidden_topics': self.forbidden_topics or [],
            'model_config_id': self.model_config_id,
            'vector_db_ids': self.vector_db_ids or [],
            'organization_id': self.organization_id,
            'org_name': self.organization.name if self.organization else None,
            'user_id': self.user_id,
            'creator_name': self.user.name if self.user else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
