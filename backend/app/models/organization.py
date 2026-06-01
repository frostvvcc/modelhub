"""
组织架构数据模型
支持层级化组织架构：学校 -> 学院 -> 系 -> 班级/教研室
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index, func, Enum as SQLEnum
from sqlalchemy.orm import relationship, backref
from app.extensions import Base
import enum


class OrganizationType(enum.Enum):
    """组织类型枚举"""
    SCHOOL = "school"  # 学校
    COLLEGE = "college"  # 学院
    MAJOR = "major"  # 专业


class OrganizationStatus(enum.Enum):
    """组织状态枚举"""
    ACTIVE = "active"  # 激活
    INACTIVE = "inactive"  # 未激活
    SUSPENDED = "suspended"  # 暂停


class Organization(Base):
    """组织架构模型"""
    __tablename__ = 'organization'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, comment="组织名称")
    code = Column(String(100), unique=True, nullable=False, comment="组织编码（唯一）")
    type = Column(String(50), nullable=False, comment="组织类型：school/college/major")
    parent_id = Column(Integer, ForeignKey('organization.id'), nullable=True, comment="父组织ID（自关联）")
    school_id = Column(Integer, ForeignKey('organization.id'), nullable=True, comment="所属学校ID（根节点）")
    level = Column(Integer, nullable=False, default=1, comment="层级深度（1=学校, 2=学院, 3=专业）")
    path = Column(String(500), nullable=True, comment="路径字符串（如：1/2/5，便于查询）")
    description = Column(String(500), nullable=True, comment="描述")
    status = Column(String(20), nullable=False, default="active", comment="状态：active/inactive/suspended")
    create_at = Column(DateTime, server_default=func.now(), nullable=False)
    update_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )
    
    # 自关联关系
    parent = relationship('Organization', remote_side=[id], foreign_keys=[parent_id], backref=backref('children', lazy='dynamic'))
    school = relationship('Organization', remote_side=[id], foreign_keys=[school_id], backref=backref('school_organizations', lazy='dynamic'))
    
    # 成员关系
    members = relationship('OrganizationMember', back_populates='organization', lazy='dynamic', cascade='all, delete-orphan')
    
    __table_args__ = (
        Index('idx_organization_parent_id', parent_id),
        Index('idx_organization_school_id', school_id),
        Index('idx_organization_type', type),
        Index('idx_organization_path', path),  # 路径索引
        Index('idx_organization_school_type', school_id, type),
        Index('idx_organization_status', status),
    )
    
    def to_dict(self, include_children=False, include_members=False, children_list=None, members_list=None):
        """转换为字典"""
        result = {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'type': self.type,
            'parent_id': self.parent_id,
            'school_id': self.school_id,
            'level': self.level,
            'path': self.path,
            'description': self.description,
            'status': self.status,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }
        
        if include_children:
            # 优先使用传入的 children_list，避免访问 lazy 关系
            if children_list is not None:
                result['children'] = [child.to_dict() if hasattr(child, 'to_dict') else child for child in children_list]
            else:
                # 尝试使用临时属性 _children
                children = getattr(self, '_children', None)
                if children:
                    result['children'] = [child.to_dict() if hasattr(child, 'to_dict') else child for child in children]
                else:
                    # 最后才尝试访问关系（可能失败）
                    try:
                        result['children'] = [child.to_dict() for child in self.children]
                    except Exception:
                        result['children'] = []
        
        if include_members:
            # 优先使用传入的 members_list，避免访问 lazy 关系
            if members_list is not None:
                result['members'] = [member.to_dict() if hasattr(member, 'to_dict') else member for member in members_list]
            else:
                # 最后才尝试访问关系（可能失败）
                try:
                    result['members'] = [member.to_dict() for member in self.members]
                except Exception:
                    result['members'] = []
        
        return result
    
    def __repr__(self):
        return f"<Organization(id={self.id}, name='{self.name}', type='{self.type}', level={self.level})>"


class OrganizationMember(Base):
    """组织成员关系模型"""
    __tablename__ = 'organization_member'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False, comment="用户ID")
    organization_id = Column(Integer, ForeignKey('organization.id'), nullable=False, comment="组织ID")
    role = Column(String(50), nullable=False, default="member", comment="角色：admin/teacher/student/guest/member")
    status = Column(String(20), nullable=False, default="active", comment="状态：active/inactive")
    join_at = Column(DateTime, server_default=func.now(), nullable=False, comment="加入时间")
    create_at = Column(DateTime, server_default=func.now(), nullable=False)
    update_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )
    
    # 关系
    user = relationship('User', backref=backref('organization_members', lazy='dynamic'))
    organization = relationship('Organization', back_populates='members')
    
    __table_args__ = (
        Index('idx_org_member_user_id', user_id),
        Index('idx_org_member_organization_id', organization_id),
        Index('idx_org_member_user_org', user_id, organization_id),
        Index('idx_org_member_org_role', organization_id, role),
    )
    
    def to_dict(self):
        """转换为字典"""
        result = {
            'id': self.id,
            'user_id': self.user_id,
            'organization_id': self.organization_id,
            'role': self.role,
            'status': self.status,
            'join_at': self.join_at.isoformat() if self.join_at else None,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }
        user = getattr(self, 'user', None)
        if user:
            result['user_name'] = user.name
            result['user_role'] = user.role
            result['student_id'] = user.student_id
            result['employee_id'] = user.employee_id
        return result
    
    def __repr__(self):
        return f"<OrganizationMember(id={self.id}, user_id={self.user_id}, organization_id={self.organization_id}, role='{self.role}')>"

