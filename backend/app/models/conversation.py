from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import relationship, backref
from app.extensions import Base


class Conversation(Base):
    __tablename__ = 'conversation'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    name = Column(String(255), nullable=True)
    model_config_id = Column(Integer, ForeignKey('model_config.id'), nullable=False)
    chat_history = Column(Integer, default=20, nullable=False)
    organization_id = Column(Integer, ForeignKey('organization.id'), nullable=True, comment="所属组织ID")
    school_id = Column(Integer, ForeignKey('organization.id'), nullable=True, comment="所属学校ID")
    create_at = Column(DateTime, server_default=func.now(), nullable=False)
    update_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )
    user = relationship('User', backref=backref('conversations', lazy=True))
    model_config = relationship('ModelConfig', backref=backref('conversations', lazy=True))
    organization = relationship('Organization', foreign_keys=[organization_id], backref=backref('conversations', lazy='dynamic'))
    school = relationship('Organization', foreign_keys=[school_id], backref=backref('school_conversations', lazy='dynamic'))
    __table_args__ = (
        Index('idx_conversation_model_config_id', model_config_id),
        Index('idx_conversation_user_id', user_id),
        Index('idx_conversation_organization_id', organization_id),
        Index('idx_conversation_school_id', school_id),
    )
