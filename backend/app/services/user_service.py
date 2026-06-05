"""
异步用户 Service
"""
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.models.user import User
from app.utils.JwtUtil import generate_jwt, authenticate_user
from app.mappers.user_mapper import AsyncUserMapper
from app.mappers.model_mapper import AsyncModelMapper
from app.mappers.vector_mapper import AsyncVectorMapper
from app.mappers.organization_mapper import AsyncOrganizationMapper
from app.services.permission_service import AsyncPermissionService
from app.utils.logger_config import get_logger
from app.utils.error_handler import (
    ConflictError,
    NotFoundError,
    UnauthorizedError,
    InternalServerError,
    ValidationError
)

logger = get_logger(__name__)


class AsyncUserService:
    """异步用户服务类"""
    
    @staticmethod
    async def register(
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
        organization_id: Optional[int] = None
    ) -> dict:
        """用户注册（学号/工号为主要标识）"""
        logger.info(f"用户注册请求: name={name}, student_id={student_id}, role={role}")

        if role == "student" and not student_id:
            raise ValidationError("学生注册必须填写学号")
        if role == "teacher" and not employee_id:
            raise ValidationError("教师注册必须填写工号")

        if school_id:
            school = await AsyncOrganizationMapper.get_organization_by_id(session, school_id)
            if not school or school.type != "school":
                raise ValidationError("指定的学校不存在")

        if organization_id:
            org = await AsyncOrganizationMapper.get_organization_by_id(session, organization_id)
            if not org:
                raise ValidationError("指定的组织不存在")
            if school_id and org.school_id != school_id and org.id != school_id:
                raise ValidationError("所选组织不属于该学校")

        enrollment_year = None
        if role == "student" and student_id:
            if len(student_id) < 4 or not student_id[:4].isdigit():
                raise ValidationError("学号格式不正确，前4位必须为入学年份数字")
            year = int(student_id[:4])
            current_year = datetime.now().year
            if year < 2000 or year > current_year:
                raise ValidationError(f"学号中的入学年份不合法（{year}），应在2000-{current_year}之间")
            enrollment_year = year

        try:
            user = await AsyncUserMapper.create_user(
                session, name, password,
                email=email,
                describe=describe,
                school_id=school_id,
                student_id=student_id,
                employee_id=employee_id,
                phone=phone,
                role=role,
                enrollment_year=enrollment_year
            )

            member_role = role if role in ("teacher", "student") else "member"
            if school_id:
                await AsyncOrganizationMapper.add_member(session, user.id, school_id, member_role)
            if organization_id and organization_id != school_id:
                await AsyncOrganizationMapper.add_member(session, user.id, organization_id, member_role)

            token = generate_jwt(user.id, user.name, user.email or "")
            logger.info(f"用户注册成功: user_id={user.id}, student_id={student_id}")

            return {
                "id": user.id,
                "name": user.name,
                "avatar": user.avatar,
                "email": user.email,
                "school_id": user.school_id,
                "token": token
            }
        except ConflictError:
            raise
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"用户注册失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"注册失败: {str(e)}")

    @staticmethod
    async def login(session: AsyncSession, account: str, password: str) -> dict:
        """用户登录（学号/工号 + 密码）"""
        logger.info(f"用户登录请求: account={account}")

        user = await AsyncUserMapper.get_user_by_account(session, account)
        if not user:
            logger.warning(f"登录失败: 用户不存在 - {account}")
            raise NotFoundError("用户不存在")

        if authenticate_user(user, account, password):
            token = generate_jwt(user.id, user.name, user.email or "")
            logger.info(f"用户登录成功: user_id={user.id}, account={account}")

            from app.mappers.permission_mapper import AsyncPermissionMapper
            user_roles = await AsyncPermissionMapper.get_user_roles(session, user.id)

            user_role = 'student'
            if user_roles:
                system_admin_role = next((ur for ur in user_roles
                                 if ur.role and ur.role.code == 'system_admin'), None)
                teacher_role = next((ur for ur in user_roles
                                   if ur.role and ur.role.code == 'teacher'), None)
                if system_admin_role:
                    user_role = 'admin'
                elif teacher_role:
                    user_role = 'teacher'
            elif user.role in {'admin', 'teacher', 'student'}:
                user_role = user.role

            return {
                "id": user.id,
                "name": user.name,
                "avatar": user.avatar,
                "email": user.email,
                "role": user_role,
                "token": token
            }
        else:
            logger.warning(f"登录失败: 密码错误 - {account}")
            raise UnauthorizedError("密码错误")
    
    @staticmethod
    async def get_user_detail(session: AsyncSession, user_id: int) -> dict:
        """获取用户详细信息（包含模型配置、向量数据库、组织和角色）"""
        logger.debug(f"获取用户信息: user_id={user_id}")

        user = await AsyncUserMapper.get_user_by_id(session, user_id)
        if not user:
            logger.warning(f"获取用户信息失败: 用户不存在 - user_id={user_id}")
            raise NotFoundError("用户不存在")
        
        # 获取模型配置（使用异步 Service）
        from app.services.model_service import AsyncModelService
        model_configs = await AsyncModelService.get_user_config(session, user)
        
        # 获取向量数据库（使用异步 Service）
        vector_dbs = await AsyncVectorMapper.get_user_vector_dbs(session, user_id)
        vector_dbs_with_docs = []
        for vector_db in vector_dbs:
            # 获取向量数据库详情（异步）
            from app.services.vector_service import AsyncVectorService
            vector_db_detail = await AsyncVectorService.get_vector_db(session, vector_db.id)
            if vector_db_detail:
                vector_dbs_with_docs.append(vector_db_detail)
        
        # 获取用户所属组织
        organizations = await AsyncOrganizationMapper.get_user_organizations(session, user_id)
        
        # 获取用户角色
        roles = await AsyncPermissionService.get_user_roles(session, user_id)
        
        # 获取用户权限
        permissions = await AsyncPermissionService.get_user_permissions(session, user_id)
        
        logger.debug(f"成功获取用户信息: user_id={user_id}")
        return {
            "user_info": user.to_dict(
                include_organizations=True, 
                include_roles=True,
                organizations_list=organizations,
                roles_list=roles
            ),
            "model_configs": model_configs,
            "vector_dbs": vector_dbs_with_docs,
            "organizations": [org.to_dict() for org in organizations],
            "roles": roles,
            "permissions": permissions
        }
    
    @staticmethod
    async def get_user_organizations(
        session: AsyncSession,
        user_id: int
    ) -> list:
        """获取用户所属的所有组织"""
        logger.debug(f"获取用户组织: user_id={user_id}")
        
        organizations = await AsyncOrganizationMapper.get_user_organizations(session, user_id)
        return [org.to_dict() for org in organizations]
    
    @staticmethod
    async def get_user_school(
        session: AsyncSession,
        user_id: int
    ) -> Optional[dict]:
        """获取用户所属学校"""
        logger.debug(f"获取用户学校: user_id={user_id}")
        
        user = await AsyncUserMapper.get_user_by_id(session, user_id)
        if not user or not user.school_id:
            return None
        
        school = await AsyncOrganizationMapper.get_organization_by_id(session, user.school_id)
        if not school:
            return None
        
        return school.to_dict()
    
    @staticmethod
    async def update_user_organization(
        session: AsyncSession,
        user_id: int,
        organization_id: int,
        role: str = "member"
    ) -> dict:
        """更新用户组织关系（添加用户到组织）"""
        logger.info(f"更新用户组织关系: user_id={user_id}, organization_id={organization_id}, role={role}")
        
        # 验证组织是否存在
        organization = await AsyncOrganizationMapper.get_organization_by_id(session, organization_id)
        if not organization:
            raise NotFoundError("组织不存在")
        
        # 添加成员
        member = await AsyncOrganizationMapper.add_member(
            session, user_id, organization_id, role
        )
        
        logger.info(f"成功更新用户组织关系")
        return member.to_dict()
    
    @staticmethod
    async def get_enterprise_users(session: AsyncSession) -> list:
        """
        获取企业用户列表
        
        Returns:
            企业用户列表
        """
        logger.debug("获取企业用户列表")
        try:
            users = await AsyncUserMapper.get_enterprise_users(session)
            logger.debug(f"成功获取企业用户列表: 共 {len(users)} 个用户")
            return [{
                "id": user.id,
                "name": user.name,
            } for user in users]
        except Exception as e:
            logger.error(f"获取企业用户列表失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"获取企业用户列表失败: {str(e)}")
    
    @staticmethod
    async def update_avatar(session: AsyncSession, user_id: int, avatar: str) -> str:
        """
        更新用户头像
        
        Raises:
            NotFoundError: 用户不存在
            InternalServerError: 更新失败
        """
        logger.info(f"更新用户头像: user_id={user_id}")
        try:
            user = await AsyncUserMapper.get_user_by_id(session, user_id)
            if not user:
                logger.warning(f"更新头像失败: 用户不存在 - user_id={user_id}")
                raise NotFoundError("用户不存在")
            
            user.avatar = avatar
            await AsyncUserMapper.update_user(session, user)
            logger.info(f"成功更新用户头像: user_id={user_id}")
            return user.avatar
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"更新用户头像失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"更新头像失败: {str(e)}")

    @staticmethod
    async def update_profile(
        session: AsyncSession,
        user_id: int,
        name: Optional[str] = None,
        describe: Optional[str] = None,
        phone: Optional[str] = None,
        student_id: Optional[str] = None,
        employee_id: Optional[str] = None,
    ) -> dict:
        """更新用户个人资料"""
        user = await AsyncUserMapper.get_user_by_id(session, user_id)
        if not user:
            raise NotFoundError("用户不存在")

        if name is not None:
            user.name = name
        if describe is not None:
            user.describe = describe
        if phone is not None:
            user.phone = phone
        if student_id is not None:
            user.student_id = student_id
            if len(student_id) >= 4 and student_id[:4].isdigit():
                year = int(student_id[:4])
                current_year = datetime.now().year
                if 2000 <= year <= current_year:
                    user.enrollment_year = year
        if employee_id is not None:
            user.employee_id = employee_id

        await AsyncUserMapper.update_user(session, user)
        return user.to_dict()

    @staticmethod
    async def change_password(
        session: AsyncSession,
        user_id: int,
        old_password: str,
        new_password: str,
    ) -> bool:
        """修改密码"""
        from app.utils.JwtUtil import verify_password, get_password_hash

        user = await AsyncUserMapper.get_user_by_id(session, user_id)
        if not user:
            raise NotFoundError("用户不存在")

        if not verify_password(old_password, user.password):
            raise ValidationError("原密码不正确")

        if len(new_password) < 6:
            raise ValidationError("新密码长度不能少于6位")

        user.password = get_password_hash(new_password)
        await AsyncUserMapper.update_user(session, user)
        return True

    @staticmethod
    async def search_users(session: AsyncSession, keyword: str = "") -> list:
        """管理员搜索用户列表"""
        from sqlalchemy import select, or_
        stmt = select(User)
        if keyword.strip():
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(User.name.ilike(like), User.email.ilike(like)))
        stmt = stmt.order_by(User.id.desc()).limit(50)
        result = await session.execute(stmt)
        users = result.scalars().all()
        return [
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "role": u.role,
                "status": u.status,
                "school_id": u.school_id,
                "create_at": u.create_at.isoformat() if u.create_at else None,
            }
            for u in users
        ]

    @staticmethod
    async def update_user_role(session: AsyncSession, user_id: int, role: str) -> dict:
        """管理员修改用户角色"""
        valid_roles = ("admin", "teacher", "student")
        if role not in valid_roles:
            raise ValidationError(f"无效角色，可选值: {', '.join(valid_roles)}")

        user = await AsyncUserMapper.get_user_by_id(session, user_id)
        if not user:
            raise NotFoundError("用户不存在")

        user.role = role
        await session.commit()
        return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}
