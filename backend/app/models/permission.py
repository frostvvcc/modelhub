"""
权限管理数据模型
支持基于角色的权限控制（RBAC）和层级权限继承
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Index, func, UniqueConstraint
from sqlalchemy.orm import relationship, backref
from app.extensions import Base


class Role(Base):
    """角色模型"""
    __tablename__ = 'role'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="角色名称")
    code = Column(String(100), unique=True, nullable=False, comment="角色代码（唯一）")
    description = Column(String(500), nullable=True, comment="描述")
    level = Column(String(50), nullable=False, default="class", comment="权限级别：system/school/college/department/class")
    is_system = Column(Boolean, default=False, nullable=False, comment="是否系统角色")
    school_id = Column(Integer, ForeignKey('organization.id'), nullable=True, comment="所属学校（系统角色为NULL）")
    create_at = Column(DateTime, server_default=func.now(), nullable=False)
    update_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )
    
    # 关系
    school = relationship('Organization', foreign_keys=[school_id], backref=backref('roles', lazy='dynamic'))
    permissions = relationship('RolePermission', back_populates='role', lazy='dynamic', cascade='all, delete-orphan')
    user_roles = relationship('UserRole', back_populates='role', lazy='dynamic', cascade='all, delete-orphan')
    
    __table_args__ = (
        Index('idx_role_code', code),
        Index('idx_role_level', level),
        Index('idx_role_school_id', school_id),
        Index('idx_role_is_system', is_system),
    )
    
    def to_dict(self, include_permissions=False):
        """转换为字典"""
        result = {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'description': self.description,
            'level': self.level,
            'is_system': self.is_system,
            'school_id': self.school_id,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }
        
        if include_permissions:
            result['permissions'] = [rp.permission.to_dict() for rp in self.permissions]
        
        return result
    
    def __repr__(self):
        return f"<Role(id={self.id}, name='{self.name}', code='{self.code}', level='{self.level}')>"


class Permission(Base):
    """权限模型"""
    __tablename__ = 'permission'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="权限名称")
    code = Column(String(100), unique=True, nullable=False, comment="权限代码（唯一，如：knowledge:read）")
    description = Column(String(500), nullable=True, comment="描述")
    resource = Column(String(50), nullable=False, comment="资源类型：knowledge/chat/config/user/organization等")
    action = Column(String(50), nullable=False, comment="操作类型：read/write/delete/manage")
    create_at = Column(DateTime, server_default=func.now(), nullable=False)
    update_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )
    
    # 关系
    role_permissions = relationship('RolePermission', back_populates='permission', lazy='dynamic', cascade='all, delete-orphan')
    
    __table_args__ = (
        Index('idx_permission_code', code),
        Index('idx_permission_resource', resource),
        Index('idx_permission_action', action),
        Index('idx_permission_resource_action', resource, action),
    )
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'description': self.description,
            'resource': self.resource,
            'action': self.action,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }
    
    def __repr__(self):
        return f"<Permission(id={self.id}, name='{self.name}', code='{self.code}')>"


class RolePermission(Base):
    """角色权限关联模型"""
    __tablename__ = 'role_permission'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    role_id = Column(Integer, ForeignKey('role.id'), nullable=False, comment="角色ID")
    permission_id = Column(Integer, ForeignKey('permission.id'), nullable=False, comment="权限ID")
    create_at = Column(DateTime, server_default=func.now(), nullable=False)
    
    # 关系
    role = relationship('Role', back_populates='permissions')
    permission = relationship('Permission', back_populates='role_permissions')
    
    __table_args__ = (
        UniqueConstraint('role_id', 'permission_id', name='uq_role_permission'),
        Index('idx_role_permission_role_id', role_id),
        Index('idx_role_permission_permission_id', permission_id),
    )
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'role_id': self.role_id,
            'permission_id': self.permission_id,
            'create_at': self.create_at.isoformat() if self.create_at else None,
        }
    
    def __repr__(self):
        return f"<RolePermission(role_id={self.role_id}, permission_id={self.permission_id})>"


class UserRole(Base):
    """用户角色关联模型"""
    __tablename__ = 'user_role'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False, comment="用户ID")
    role_id = Column(Integer, ForeignKey('role.id'), nullable=False, comment="角色ID")
    organization_id = Column(Integer, ForeignKey('organization.id'), nullable=True, comment="组织ID（可选，用于组织级角色）")
    scope = Column(String(50), nullable=True, comment="作用域：system/school/college/department/class")
    is_active = Column(Boolean, default=True, nullable=False, comment="是否激活")
    create_at = Column(DateTime, server_default=func.now(), nullable=False)
    update_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )
    
    # 关系
    user = relationship('User', backref=backref('user_roles', lazy='dynamic'))
    role = relationship('Role', back_populates='user_roles')
    organization = relationship('Organization', foreign_keys=[organization_id], backref=backref('user_roles', lazy='dynamic'))
    
    __table_args__ = (
        Index('idx_user_role_user_id', user_id),
        Index('idx_user_role_role_id', role_id),
        Index('idx_user_role_organization_id', organization_id),
        Index('idx_user_role_user_org_role', user_id, organization_id, role_id),
        Index('idx_user_role_is_active', is_active),
    )
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'role_id': self.role_id,
            'role_code': self.role.code if self.role else None,
            'role_name': self.role.name if self.role else None,
            'organization_id': self.organization_id,
            'scope': self.scope,
            'is_active': self.is_active,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }
    
    def __repr__(self):
        return f"<UserRole(user_id={self.user_id}, role_id={self.role_id}, organization_id={self.organization_id})>"
