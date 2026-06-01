"""
教学空间数据模型
老师创建教学空间 → 绑定专业 → 分发资源给学生
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import relationship, backref
from app.extensions import Base


class TeachingSpace(Base):
    """教学空间"""
    __tablename__ = 'teaching_space'

    id = Column(Integer, primary_key=True, autoincrement=True)
    space_code = Column(String(20), unique=True, nullable=True, comment="结构化编号，如 CS-25-001")
    name = Column(String(255), nullable=False, comment="空间名称")
    description = Column(Text, nullable=True, comment="空间描述")
    teacher_id = Column(Integer, ForeignKey('user.id'), nullable=False, comment="创建者（老师）")
    school_id = Column(Integer, ForeignKey('organization.id'), nullable=True, comment="所属学校")
    status = Column(String(20), nullable=False, default="active", comment="状态：active/archived")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )

    teacher = relationship('User', backref=backref('teaching_spaces', lazy='dynamic'))
    school = relationship('Organization', foreign_keys=[school_id])

    __table_args__ = (
        Index('idx_teaching_space_teacher_id', teacher_id),
        Index('idx_teaching_space_school_id', school_id),
        Index('idx_teaching_space_status', status),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'space_code': self.space_code,
            'name': self.name,
            'description': self.description,
            'teacher_id': self.teacher_id,
            'teacher_name': self.teacher.name if self.teacher else None,
            'school_id': self.school_id,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class TeachingSpaceMajor(Base):
    """教学空间-专业绑定"""
    __tablename__ = 'teaching_space_major'

    id = Column(Integer, primary_key=True, autoincrement=True)
    space_id = Column(Integer, ForeignKey('teaching_space.id', ondelete='CASCADE'), nullable=False)
    major_id = Column(Integer, ForeignKey('organization.id'), nullable=False, comment="绑定的专业组织ID")
    enrollment_year = Column(Integer, nullable=True, comment="绑定的年级（入学年份），NULL表示该专业全部年级")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    space = relationship('TeachingSpace', backref=backref('bound_majors', lazy='dynamic', cascade='all, delete-orphan'))
    major = relationship('Organization', foreign_keys=[major_id])

    __table_args__ = (
        UniqueConstraint('space_id', 'major_id', 'enrollment_year', name='uq_space_major_year'),
        Index('idx_ts_major_space_id', space_id),
        Index('idx_ts_major_major_id', major_id),
        Index('idx_ts_major_enrollment_year', enrollment_year),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'space_id': self.space_id,
            'major_id': self.major_id,
            'major_name': self.major.name if self.major else None,
            'major_code': self.major.code if self.major else None,
            'enrollment_year': self.enrollment_year,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class TeachingSpaceStudent(Base):
    """教学空间-学生直接绑定（管理员手动添加）"""
    __tablename__ = 'teaching_space_student'

    id = Column(Integer, primary_key=True, autoincrement=True)
    space_id = Column(Integer, ForeignKey('teaching_space.id', ondelete='CASCADE'), nullable=False)
    student_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    space = relationship('TeachingSpace', backref=backref('direct_students', lazy='dynamic', cascade='all, delete-orphan'))
    student = relationship('User', foreign_keys=[student_id])

    __table_args__ = (
        UniqueConstraint('space_id', 'student_id', name='uq_space_student'),
        Index('idx_ts_student_space_id', space_id),
        Index('idx_ts_student_student_id', student_id),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'space_id': self.space_id,
            'student_id': self.student_id,
            'student_name': self.student.name if self.student else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class TeachingSpaceResource(Base):
    """教学空间-资源分发"""
    __tablename__ = 'teaching_space_resource'

    id = Column(Integer, primary_key=True, autoincrement=True)
    space_id = Column(Integer, ForeignKey('teaching_space.id', ondelete='CASCADE'), nullable=False)
    resource_type = Column(String(20), nullable=False, comment="资源类型：vector_db / bot")
    resource_id = Column(Integer, nullable=False, comment="资源ID")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    space = relationship('TeachingSpace', backref=backref('resources', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        UniqueConstraint('space_id', 'resource_type', 'resource_id', name='uq_space_resource'),
        Index('idx_ts_resource_space_id', space_id),
        Index('idx_ts_resource_type_id', resource_type, resource_id),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'space_id': self.space_id,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
