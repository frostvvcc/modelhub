from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Index, func, Boolean
from sqlalchemy.orm import relationship, backref
from app.extensions import Base

class Document(Base):
    __tablename__ = 'document'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    vector_db_id = Column(Integer, ForeignKey('vector_db.id'), nullable=False)
    name = Column(String(255), nullable=False)  # 移除 unique，允许同名文件在不同文件夹
    original_name = Column(String(255), nullable=True)  # 文件夹可以为空
    type = Column(String(64), nullable=True)  # 文件夹可以为空
    size = Column(Integer, nullable=True, default=0)  # 文件夹大小为0
    save_path = Column(Text, nullable=True)  # 文件夹可以为空
    describe = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="success", comment="状态：processing/success/failed/archived")
    error_message = Column(Text, nullable=True, comment="解析或向量化失败原因")
    archived_at = Column(DateTime, nullable=True, comment="归档时间")
    # 层级结构字段
    parent_id = Column(Integer, ForeignKey('document.id'), nullable=True, comment="父文件夹ID")
    is_folder = Column(Boolean, default=False, nullable=False, comment="是否为文件夹")
    folder_path = Column(String(500), nullable=True, comment="文件夹路径（如：1/2/5）")
    upload_at = Column(DateTime, server_default=func.now(), nullable=False)
    user = relationship('User', backref=backref('documents', lazy=True))
    vector_db = relationship('VectorDb', back_populates='stored_documents')
    # 自关联关系
    parent = relationship('Document', remote_side=[id], foreign_keys=[parent_id], backref=backref('children', lazy='dynamic'))
    __table_args__ = (
        Index('idx_document_type', type),
        Index('idx_document_upload_at', upload_at),
        Index('idx_document_user_id', user_id),
        Index('idx_document_vector_db_id', vector_db_id),
        Index('idx_document_parent_id', parent_id),
        Index('idx_document_folder_path', folder_path),
        Index('idx_document_is_folder', is_folder),
        Index('idx_document_status', status),
    )

    def to_dict(self, include_children=False):
        upload_at_str = self.upload_at.strftime('%Y-%m-%d %H:%M:%S') if self.upload_at else None
        result = {
            'id': self.id,
            'name': self.name,
            'original_name': self.original_name,
            'type': self.type,
            'size': self.size or 0,
            'save_path': self.save_path,
            'describe': self.describe,
            'status': self.status or 'success',
            'error_message': self.error_message,
            'archived_at': self.archived_at.strftime('%Y-%m-%d %H:%M:%S') if self.archived_at else None,
            'upload_at': upload_at_str,
            'parent_id': self.parent_id,
            'is_folder': self.is_folder,
            'folder_path': self.folder_path,
        }
        if include_children and self.is_folder:
            try:
                result['children'] = [child.to_dict(include_children=True) for child in self.children]
            except Exception:
                result['children'] = []
        return result
