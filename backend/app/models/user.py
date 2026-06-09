from sqlalchemy import Column, Integer, String, DateTime, Index, func, ForeignKey
from sqlalchemy.orm import relationship, backref
from app.extensions import Base

type_map = {
    1:  'Individual',
    2:  'Enterprise',
}

class User(Base):
    __tablename__ = 'user'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    avatar = Column(String(255), nullable=True)
    password = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    describe = Column(String(255), nullable=True)
    type = Column(Integer, nullable=True)  # 保留用于兼容
    # 新增字段
    role = Column(String(20), nullable=True, default="student", comment="用户角色：admin/teacher/student")
    school_id = Column(Integer, ForeignKey('organization.id'), nullable=True, comment="所属学校ID")
    student_id = Column(String(50), nullable=True, comment="学号")
    employee_id = Column(String(50), nullable=True, comment="工号")
    phone = Column(String(20), nullable=True, comment="手机号")
    enrollment_year = Column(Integer, nullable=True, comment="入学年份，由学号前4位自动识别")
    status = Column(String(20), nullable=False, default="active", comment="用户状态：active/inactive/suspended")
    token_version = Column(Integer, nullable=False, default=0, server_default="0", comment="Token版本号，修改密码时递增")
    create_at = Column(DateTime, server_default=func.now(), nullable=False)
    update_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )
    
    # 关系
    school = relationship('Organization', foreign_keys=[school_id], backref=backref('school_users', lazy='dynamic'))
    
    __table_args__ = (
        Index('idx_user_create_at', create_at),
        Index('idx_user_update_at', update_at),
        Index('idx_user_school_id', school_id),
        Index('idx_user_student_id', student_id),
        Index('idx_user_employee_id', employee_id),
        Index('idx_user_status', status),
        Index('idx_user_email', email),
        Index('idx_user_role', role),
        Index('idx_user_enrollment_year', enrollment_year),
    )

    def to_dict(self, include_organizations=False, include_roles=False, organizations_list=None, roles_list=None):
        """转换为字典"""
        result = {
            'id': self.id,
            'name': self.name,
            'avatar': self.avatar,
            'email': self.email,
            'describe': self.describe,
            'type': type_map.get(self.type, 'Unknown') if self.type is not None else None,
            'role': self.role,  # 新增：直接返回角色
            'school_id': self.school_id,
            'student_id': self.student_id,
            'employee_id': self.employee_id,
            'phone': self.phone,
            'enrollment_year': self.enrollment_year,
            'status': self.status,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }

        # 使用传入的组织列表，避免访问 lazy 关系
        if include_organizations:
            if organizations_list:
                result['organizations'] = [org.to_dict() if hasattr(org, 'to_dict') else org for org in organizations_list]
            else:
                # 如果没有传入，尝试访问关系（可能失败）
                try:
                    result['organizations'] = [om.organization.to_dict() for om in self.organization_members]
                except Exception:
                    result['organizations'] = []

        # 为了向后兼容，保留roles字段（但标记为废弃）
        if include_roles:
            if roles_list:
                result['roles'] = [role.to_dict() if hasattr(role, 'to_dict') else role for role in roles_list]
            else:
                # 如果没有传入，尝试访问关系（可能失败）
                try:
                    result['roles'] = [ur.role.to_dict() for ur in self.user_roles if ur.is_active]
                except Exception:
                    result['roles'] = []

        return result
