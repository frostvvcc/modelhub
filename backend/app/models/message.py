from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Index, func
from sqlalchemy.orm import relationship, backref
from app.extensions import Base


class Message(Base):
    __tablename__ = 'message'
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey('conversation.id'), nullable=False)
    role = Column(String(10), nullable=False)  # 可扩展为枚举校验
    content = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    create_at = Column(DateTime, server_default=func.now(), nullable=False)
    conversation = relationship('Conversation', backref=backref('messages', lazy=True))
    __table_args__ = (
        Index('idx_message_conversation_id', conversation_id),
        Index('idx_message_role', role),
    )
