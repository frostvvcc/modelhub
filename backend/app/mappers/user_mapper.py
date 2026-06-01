"""
异步用户 Mapper
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.models.user import User
from app.utils.JwtUtil import get_password_hash
from app.utils.async_db import AsyncDB
import logging

logger = logging.getLogger(__name__)


class AsyncUserMapper:
    """异步用户数据访问层"""

    @staticmethod
    def _get_default_role(email: str) -> str:
        """
        根据邮箱确定默认用户角色

        Args:
            email: 用户邮箱

        Returns:
            用户角色（admin/teacher/student）
        """
        # 管理员邮箱列表（根据实际情况修改）
        admin_emails = ["admin@example.com", "root@example.com"]
        if email.lower() in [e.lower() for e in admin_emails]:
            return "admin"

        # 教师邮箱规则（可根据域名或其他规则判断）
        teacher_domains = ["teacher.", "edu.", "faculty.", "staff."]
        if any(domain in email.lower() for domain in teacher_domains):
            return "teacher"

        # 默认为学生
        return "student"

    @staticmethod
    async def get_user_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
        """根据 ID 获取用户"""
        return await AsyncDB.get_by_id(session, User, user_id)

    @staticmethod
    async def get_user_by_email(session: AsyncSession, email: str) -> Optional[User]:
        """根据邮箱获取用户"""
        return await AsyncDB.get_by_field(session, User, "email", email)

    @staticmethod
    async def get_user_by_account(session: AsyncSession, account: str) -> Optional[User]:
        """根据学号/工号/邮箱查找用户"""
        stmt = select(User).where(
            or_(
                User.student_id == account,
                User.employee_id == account,
                User.email == account
            )
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_user_by_student_id(session: AsyncSession, student_id: str) -> Optional[User]:
        """根据学号获取用户"""
        return await AsyncDB.get_by_field(session, User, "student_id", student_id)

    @staticmethod
    async def create_user(
        session: AsyncSession,
        name: str,
        password: str,
        email: Optional[str] = None,
        describe: Optional[str] = None,
        school_id: Optional[int] = None,
        student_id: Optional[str] = None,
        employee_id: Optional[str] = None,
        phone: Optional[str] = None,
        role: Optional[str] = None,
        enrollment_year: Optional[int] = None
    ) -> User:
        """创建用户（支持组织关联）"""
        if email:
            existing_user = await AsyncUserMapper.get_user_by_email(session, email)
            if existing_user:
                raise ValueError("该邮箱已注册")

        if student_id:
            existing = await AsyncUserMapper.get_user_by_student_id(session, student_id)
            if existing:
                raise ValueError("该学号已注册")

        if employee_id:
            existing = await AsyncDB.get_by_field(session, User, "employee_id", employee_id)
            if existing:
                raise ValueError("该工号已注册")

        try:
            if role and role in ("student", "teacher", "admin"):
                default_role = role
            elif email:
                default_role = AsyncUserMapper._get_default_role(email)
            else:
                default_role = "student"

            user = User(
                name=name,
                email=email,
                password=get_password_hash(password),
                describe=describe,
                role=default_role,
                school_id=school_id,
                student_id=student_id,
                employee_id=employee_id,
                phone=phone,
                enrollment_year=enrollment_year,
                status="active"
            )
            user = await AsyncDB.create(session, user)
            await AsyncDB.commit(session)
            return user
        except Exception as e:
            await AsyncDB.rollback(session)
            raise Exception(f"创建用户失败: {str(e)}")
    
    @staticmethod
    async def get_enterprise_users(session: AsyncSession) -> list[User]:
        """获取企业用户列表"""
        return await AsyncDB.filter_by(session, User, type=2)
    
    @staticmethod
    async def update_user(session: AsyncSession, user: User) -> User:
        """更新用户"""
        try:
            user = await AsyncDB.update(session, user)
            await AsyncDB.commit(session)
            return user
        except Exception as e:
            await AsyncDB.rollback(session)
            raise Exception(f"更新用户失败: {str(e)}")

