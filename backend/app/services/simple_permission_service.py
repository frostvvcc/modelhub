"""
简化权限管理 Service
基于 organization_id 决定可见范围：
- organization_id 指向学校 → 全校可见
- organization_id 指向学院 → 学院成员可见
- organization_id = NULL → 私有（仅创建者，或通过教学空间发布给学生）
"""
from enum import Enum
from typing import List, Optional, Dict, Any, Union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException, status

from app.mappers.user_mapper import AsyncUserMapper
from app.mappers.vector_mapper import AsyncVectorMapper
from app.models.user import User
from app.models.vector_db import VectorDb
from app.models.document import Document
from app.models.model_config import ModelConfig
from app.models.organization import Organization, OrganizationMember
from app.utils.logger_config import get_logger
from app.utils.error_handler import (
    NotFoundError,
    ValidationError,
    InternalServerError
)

logger = get_logger(__name__)


class UserRole(str, Enum):
    """用户角色枚举"""
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"


ADMIN_ROLES = {UserRole.ADMIN}


class SimplePermissionService:
    """简化权限管理服务类"""

    # ------------------------------------------------------------------
    # 角色判断
    # ------------------------------------------------------------------

    @staticmethod
    async def get_user_role(db: AsyncSession, user: User) -> UserRole:
        """获取用户角色。"""
        if hasattr(user, 'role') and user.role:
            try:
                return UserRole(user.role)
            except ValueError:
                pass
        return UserRole.STUDENT

    @staticmethod
    async def _resolve_role_string(db: AsyncSession, user_id: int) -> str:
        user = await AsyncUserMapper.get_user_by_id(db, user_id)
        if not user:
            return 'student'
        return (await SimplePermissionService.get_user_role(db, user)).value

    # ------------------------------------------------------------------
    # 核心：检查用户是否能看到某个资源
    # 规则：
    # 1. 用户是创建者 → 可见
    # 2. 用户是 admin → 可见
    # 3. organization_id 不为空 → 用户属于该组织或其子组织 → 可见
    # 4. 资源通过教学空间发布 → 用户属于该教学空间绑定的专业 → 可见
    # 5. 否则 → 不可见
    # ------------------------------------------------------------------

    @staticmethod
    async def _user_belongs_to_org(db: AsyncSession, user_id: int, user: User, org_id: int) -> bool:
        """检查用户是否属于指定组织（含层级关系）"""
        org = await db.get(Organization, org_id)
        if not org:
            return False

        # 如果资源归属学校级别，检查用户是否属于该学校
        if org.type == "school":
            if user.school_id == org_id:
                return True
            stmt = select(OrganizationMember).where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == org_id
            )
            result = await db.execute(stmt)
            if result.first() is not None:
                return True
            # 用户属于该学校的子组织也算
            stmt2 = select(OrganizationMember).join(
                Organization, OrganizationMember.organization_id == Organization.id
            ).where(
                OrganizationMember.user_id == user_id,
                Organization.school_id == org_id
            )
            result2 = await db.execute(stmt2)
            return result2.first() is not None

        # 如果资源归属学院/专业级别
        # 直接成员
        stmt = select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id
        )
        result = await db.execute(stmt)
        if result.first() is not None:
            return True

        # 用户属于该组织的子组织（如：资源归属学院，用户属于学院下的专业）
        if org.path:
            org_path_prefix = f"{org.path}/{org_id}"
        else:
            org_path_prefix = str(org_id)

        user_orgs_stmt = select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == user_id
        )
        user_orgs_result = await db.execute(user_orgs_stmt)
        user_org_ids = [row[0] for row in user_orgs_result.fetchall()]

        for user_org_id in user_org_ids:
            user_org = await db.get(Organization, user_org_id)
            if user_org and user_org.path:
                if str(org_id) in user_org.path.split('/'):
                    return True

        return False

    @staticmethod
    async def _user_has_teaching_space_access(db: AsyncSession, user_id: int, resource_type: str, resource_id: int) -> bool:
        """检查用户是否通过教学空间有权访问该资源"""
        from app.models.teaching_space import TeachingSpaceMajor, TeachingSpaceResource

        stmt = select(TeachingSpaceResource.space_id).where(
            TeachingSpaceResource.resource_type == resource_type,
            TeachingSpaceResource.resource_id == resource_id
        )
        result = await db.execute(stmt)
        space_ids = [row[0] for row in result.fetchall()]
        if not space_ids:
            return False

        major_stmt = select(TeachingSpaceMajor.major_id).where(
            TeachingSpaceMajor.space_id.in_(space_ids)
        )
        major_result = await db.execute(major_stmt)
        major_ids = [row[0] for row in major_result.fetchall()]
        if not major_ids:
            return False

        member_stmt = select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id.in_(major_ids)
        )
        member_result = await db.execute(member_stmt)
        return member_result.first() is not None

    @staticmethod
    async def check_resource_access(
        db: AsyncSession,
        user: User,
        resource: Union[VectorDb, ModelConfig],
        user_role: Optional[UserRole] = None
    ) -> bool:
        """检查用户对资源的访问权限。"""
        if not user_role:
            user_role = await SimplePermissionService.get_user_role(db, user)

        # 1. admin 全权
        if user_role in ADMIN_ROLES:
            return True

        # 2. 创建者
        owner_id = getattr(resource, 'user_id', None)
        if owner_id and owner_id == user.id:
            return True

        # 3. 根据 organization_id 判断
        org_id = getattr(resource, 'organization_id', None)
        if org_id:
            if await SimplePermissionService._user_belongs_to_org(db, user.id, user, org_id):
                return True

        # 4. 通过教学空间访问
        resource_type = "vector_db" if isinstance(resource, VectorDb) else "bot"
        if await SimplePermissionService._user_has_teaching_space_access(db, user.id, resource_type, resource.id):
            return True

        return False

    @staticmethod
    async def check_operation_permission(
        db: AsyncSession,
        user: User,
        operation: str,
        resource: Optional[Union[VectorDb, ModelConfig]] = None,
        user_role: Optional[UserRole] = None
    ) -> bool:
        """检查用户是否可执行某操作（create/update/delete/read/list）。"""
        if not user_role:
            user_role = await SimplePermissionService.get_user_role(db, user)

        if user_role in ADMIN_ROLES:
            return True

        if operation in ["create", "update", "delete"]:
            if user_role == UserRole.STUDENT:
                return False
            if user_role == UserRole.TEACHER:
                if resource:
                    owner_id = getattr(resource, 'user_id', None)
                    return bool(owner_id and owner_id == user.id)
                return True

        if operation in ["read", "list"]:
            return True

        return False

    # ------------------------------------------------------------------
    # 知识库专用权限
    # ------------------------------------------------------------------

    @staticmethod
    async def check_vector_db_access(
        session: AsyncSession,
        user_id: int,
        vector_db_id: int
    ) -> bool:
        """知识库访问权限检查。"""
        try:
            user = await AsyncUserMapper.get_user_by_id(session, user_id)
            vector_db = await AsyncVectorMapper.get_vector_db(session, vector_db_id)

            if not user or not vector_db:
                return False

            user_role = await SimplePermissionService.get_user_role(session, user)

            # admin 全权
            if user_role in ADMIN_ROLES:
                return True
            # 创建者
            if vector_db.user_id == user_id:
                return True
            # 根据 organization_id
            if vector_db.organization_id:
                if await SimplePermissionService._user_belongs_to_org(session, user_id, user, vector_db.organization_id):
                    return True
            # 教学空间
            if await SimplePermissionService._user_has_teaching_space_access(session, user_id, "vector_db", vector_db_id):
                return True

            return False
        except Exception as e:
            logger.error(f"权限检查异常: {str(e)}", exc_info=True)
            return False

    @staticmethod
    async def can_upload_document(
        session: AsyncSession,
        user_id: int,
        vector_db_id: int
    ) -> bool:
        """检查用户是否可以向知识库上传文档。只有创建者和 admin 可以上传。"""
        try:
            user = await AsyncUserMapper.get_user_by_id(session, user_id)
            vector_db = await AsyncVectorMapper.get_vector_db(session, vector_db_id)
            if not user or not vector_db:
                return False

            role = await SimplePermissionService.get_user_role(session, user)
            if role in ADMIN_ROLES:
                return True
            if vector_db.user_id == user_id:
                return True
            return False
        except Exception as e:
            logger.error(f"文档上传权限检查异常: {str(e)}", exc_info=True)
            return False

    @staticmethod
    async def can_delete_document(
        session: AsyncSession,
        user_id: int,
        document_id: int
    ) -> bool:
        """检查用户是否可以删除文档。"""
        try:
            user = await AsyncUserMapper.get_user_by_id(session, user_id)
            document = await AsyncVectorMapper.get_document_by_id(session, document_id)
            if not user or not document:
                return False

            role = await SimplePermissionService.get_user_role(session, user)
            if role in ADMIN_ROLES:
                return True
            if document.user_id == user_id:
                return True
            vector_db = await AsyncVectorMapper.get_vector_db(session, document.vector_db_id)
            if vector_db and vector_db.user_id == user_id:
                return True
            return False
        except Exception as e:
            logger.error(f"文档删除权限检查异常: {str(e)}", exc_info=True)
            return False

    @staticmethod
    async def get_accessible_vector_dbs(
        session: AsyncSession,
        user_id: int
    ) -> List[Dict[str, Any]]:
        """获取用户可访问的知识库列表。"""
        try:
            user = await AsyncUserMapper.get_user_by_id(session, user_id)
            if not user:
                return []

            user_role = await SimplePermissionService.get_user_role(session, user)

            # admin 看全部
            if user_role in ADMIN_ROLES:
                from sqlalchemy.orm import selectinload
                stmt = select(VectorDb).options(selectinload(VectorDb.user), selectinload(VectorDb.organization))
                result = await session.execute(stmt)
                all_dbs = list(result.scalars().all())
            else:
                # 获取用户所属的所有组织 ID（含层级）
                user_org_ids: set = set()
                if user.school_id:
                    user_org_ids.add(user.school_id)
                user_orgs_stmt = select(OrganizationMember.organization_id).where(
                    OrganizationMember.user_id == user_id
                )
                user_orgs_result = await session.execute(user_orgs_stmt)
                for row in user_orgs_result.fetchall():
                    user_org_ids.add(row[0])
                    org = await session.get(Organization, row[0])
                    if org:
                        if org.school_id:
                            user_org_ids.add(org.school_id)
                        if org.path:
                            for ancestor_id in org.path.split('/'):
                                if ancestor_id:
                                    user_org_ids.add(int(ancestor_id))

                # 获取通过教学空间可访问的知识库 ID
                from app.models.teaching_space import TeachingSpaceMajor, TeachingSpaceResource
                ts_major_stmt = select(TeachingSpaceMajor.space_id).where(
                    TeachingSpaceMajor.major_id.in_(user_org_ids)
                ) if user_org_ids else None

                teaching_space_vdb_ids: set = set()
                if ts_major_stmt is not None:
                    ts_result = await session.execute(ts_major_stmt)
                    space_ids = [row[0] for row in ts_result.fetchall()]
                    if space_ids:
                        res_stmt = select(TeachingSpaceResource.resource_id).where(
                            TeachingSpaceResource.space_id.in_(space_ids),
                            TeachingSpaceResource.resource_type == "vector_db"
                        )
                        res_result = await session.execute(res_stmt)
                        teaching_space_vdb_ids = {row[0] for row in res_result.fetchall()}

                # 查询：用户创建的 + 归属组织的 + 教学空间的
                from sqlalchemy import or_
                from sqlalchemy.orm import selectinload
                conditions = [VectorDb.user_id == user_id]
                if user_org_ids:
                    conditions.append(VectorDb.organization_id.in_(user_org_ids))
                if teaching_space_vdb_ids:
                    conditions.append(VectorDb.id.in_(teaching_space_vdb_ids))

                stmt = select(VectorDb).options(
                    selectinload(VectorDb.user), selectinload(VectorDb.organization)
                ).where(or_(*conditions))
                result = await session.execute(stmt)
                all_dbs = list(result.scalars().all())

            # 统计文档数
            db_ids = [db.id for db in all_dbs]
            doc_counts: Dict[int, int] = {}
            if db_ids:
                count_stmt = (
                    select(Document.vector_db_id, func.count(Document.id))
                    .where(Document.vector_db_id.in_(db_ids), Document.is_folder == False)
                    .group_by(Document.vector_db_id)
                )
                count_result = await session.execute(count_stmt)
                doc_counts = dict(count_result.all())

            return [
                {
                    'id': db.id,
                    'name': db.name,
                    'describe': db.describe,
                    'user_id': db.user_id,
                    'creator_name': db.user.name if db.user else None,
                    'embedding_id': db.embedding_id,
                    'document_similarity': float(db.document_similarity) if db.document_similarity else None,
                    'organization_id': db.organization_id,
                    'org_name': db.organization.name if db.organization else None,
                    'created_at': db.create_at.isoformat() if db.create_at else None,
                    'updated_at': db.update_at.isoformat() if db.update_at else None,
                    'document_count': doc_counts.get(db.id, 0),
                }
                for db in all_dbs
            ]
        except Exception as e:
            logger.error(f"获取可访问知识库列表异常: {str(e)}", exc_info=True)
            return []

    @staticmethod
    async def check_vector_db_creation_permission(
        session: AsyncSession,
        user_id: int,
        organization_id: Optional[int] = None
    ) -> bool:
        """检查用户是否有权限创建知识库。老师和 admin 可以创建。"""
        try:
            user_role = await SimplePermissionService._resolve_role_string(session, user_id)
            if user_role == 'admin':
                return True
            if user_role == 'teacher':
                return True
            return False
        except Exception as e:
            logger.error(f"知识库创建权限检查异常: {str(e)}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # 装饰器工厂
    # ------------------------------------------------------------------

    @staticmethod
    def require_role(*allowed_roles: UserRole):
        """角色限制装饰器工厂。"""
        def decorator(func):
            async def wrapper(*args, **kwargs):
                current_user = kwargs.get('current_user')
                db = kwargs.get('db')
                if not current_user or not db:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Database session or user not found"
                    )
                user_role = await SimplePermissionService.get_user_role(db, current_user)
                if user_role not in allowed_roles:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"权限不足，需要角色: {[r.value for r in allowed_roles]}"
                    )
                return await func(*args, **kwargs)
            return wrapper
        return decorator

    @staticmethod
    def require_operation(operation: str):
        """操作权限装饰器工厂。"""
        def decorator(func):
            async def wrapper(*args, **kwargs):
                current_user = kwargs.get('current_user')
                db = kwargs.get('db')
                resource = (kwargs.get('resource')
                            or kwargs.get('vector_db')
                            or kwargs.get('model_config'))
                if not current_user or not db:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Database session or user not found"
                    )
                has_permission = await SimplePermissionService.check_operation_permission(
                    db, current_user, operation, resource
                )
                if not has_permission:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"权限不足，无法执行操作: {operation}"
                    )
                return await func(*args, **kwargs)
            return wrapper
        return decorator


# ------------------------------------------------------------------
# 便捷函数
# ------------------------------------------------------------------

async def check_resource_access(
    db: AsyncSession,
    user: User,
    resource: Union[VectorDb, ModelConfig],
    user_role: Optional[UserRole] = None
) -> bool:
    return await SimplePermissionService.check_resource_access(db, user, resource, user_role)


async def check_operation_permission(
    db: AsyncSession,
    user: User,
    operation: str,
    resource: Optional[Union[VectorDb, ModelConfig]] = None,
    user_role: Optional[UserRole] = None
) -> bool:
    return await SimplePermissionService.check_operation_permission(
        db, user, operation, resource, user_role
    )
