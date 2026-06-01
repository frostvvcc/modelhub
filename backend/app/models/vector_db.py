import decimal
from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey, Index, func
from sqlalchemy.orm import relationship, backref
from app.extensions import Base
from datetime import datetime

class VectorDb(Base):
    __tablename__ = 'vector_db'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    embedding_id = Column(Integer, ForeignKey('model_info.id'), nullable=False)
    name = Column(String(255), nullable=False)
    document_similarity = Column(Numeric(5, 2), default=decimal.Decimal('0.50'), nullable=True)
    describe = Column(String(255), nullable=True)
    organization_id = Column(Integer, ForeignKey('organization.id'), nullable=True, comment="归属组织ID：NULL=私有，学校ID=全校可见，学院ID=学院可见")
    stored_documents = relationship('Document', back_populates='vector_db', lazy=True)
    create_at = Column(DateTime, server_default=func.now(), nullable=False)
    update_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )
    user = relationship('User', backref=backref('vector_dbs', lazy=True))
    organization = relationship('Organization', foreign_keys=[organization_id], backref=backref('vector_dbs', lazy='dynamic'))
    __table_args__ = (
        Index('idx_vector_db_create_at', create_at),
        Index('idx_user_id', user_id),
        Index('idx_vector_db_organization_id', organization_id),
    )

    def to_dict(self, include_documents=False, documents_list=None):
        created_at_str = self.create_at.strftime('%Y-%m-%d %H:%M:%S') if self.create_at else None
        updated_at_str = self.update_at.strftime('%Y-%m-%d %H:%M:%S') if self.update_at else None

        result = {
            'id': self.id,
            'name': self.name,
            'describe': self.describe,
            'embedding_id': self.embedding_id,
            'document_similarity': float(self.document_similarity) if self.document_similarity else None,
            'user_id': self.user_id,
            'creator_name': self.user.name if self.user else None,
            'organization_id': self.organization_id,
            'org_name': self.organization.name if self.organization else None,
            'created_at': created_at_str,
            'updated_at': updated_at_str,
        }

        if include_documents:
            if documents_list is not None:
                result['documents'] = [doc.to_dict() if hasattr(doc, 'to_dict') else doc for doc in documents_list]
            else:
                try:
                    result['documents'] = [doc.to_dict() for doc in self.stored_documents]
                except Exception:
                    result['documents'] = []
        else:
            result['documents'] = []

        return result
