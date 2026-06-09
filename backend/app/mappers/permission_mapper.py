"""
异步权限管理 Mapper
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, distinct
from sqlalchemy.orm import selectinload
from typing import List, Optional, Set
from app.models.permission import Role, Permission, RolePermission, UserRole
from app.models.organization import Organization
from app.utils.async_db import AsyncDB
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


class AsyncPermissionMapper:
    """异步权限管理数据访问层"""
    
    # Role 相关方法
    @staticmethod
    async def get_role_by_id(session: AsyncSession, role_id: int) -> Optional[Role]:
        """根据 ID 获取角色"""
        return await AsyncDB.get_by_id(session, Role, role_id)
    
    @staticmethod
    async def get_role_by_code(session: AsyncSession, code: str) -> Optional[Role]:
        """根据编码获取角色"""
        return await AsyncDB.get_by_field(session, Role, "code", code)
    
    @staticmethod
    async def create_role(
        session: AsyncSession,
        name: str,
        code: str,
        description: Optional[str] = None,
        level: str = "class",
        is_system: bool = False,
        school_id: Optional[int] = None
    ) -> Role:
        """创建角色"""
        # 检查编码是否已存在
        existing = await AsyncPermissionMapper.get_role_by_code(session, code)
        if existing:
            raise ValueError(f"Role code '{code}' already exists")
        
        # 如果创建系统级角色（level='system'），检查是否已存在系统级角色
        if level == "system" or is_system:
            stmt = select(Role).where(
                and_(
                    Role.level == "system",
                    Role.is_system == True
                )
            )
            result = await session.execute(stmt)
            system_role = result.scalar_one_or_none()
            if system_role:
                raise ValueError("系统只能有一个顶级角色（level='system'），已存在系统级角色")
        
        role = Role(
            name=name,
            code=code,
            description=description,
            level=level,
            is_system=is_system,
            school_id=school_id
        )
        role = await AsyncDB.create(session, role)
        await AsyncDB.commit(session)
        return role
    
    @staticmethod
    async def get_roles(
        session: AsyncSession,
        school_id: Optional[int] = None,
        include_system: bool = True
    ) -> List[Role]:
        """获取角色列表"""
        stmt = select(Role)

        if school_id is not None:
            if include_system:
                # school_id 匹配 OR 系统角色
                stmt = stmt.where(
                    or_(Role.school_id == school_id, Role.is_system == True)
                )
            else:
                # 仅 school_id 匹配，排除系统角色
                stmt = stmt.where(
                    and_(Role.school_id == school_id, Role.is_system == False)
                )
        else:
            if not include_system:
                # 无 school_id，排除系统角色
                stmt = stmt.where(Role.is_system == False)
        
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def update_role(
        session: AsyncSession,
        role_id: int,
        **kwargs
    ) -> Role:
        """更新角色"""
        role = await AsyncPermissionMapper.get_role_by_id(session, role_id)
        if not role:
            raise ValueError(f"Role with id {role_id} not found")
        
        for key, value in kwargs.items():
            if hasattr(role, key) and value is not None:
                setattr(role, key, value)

        await AsyncDB.commit(session)
        await session.refresh(role)
        return role

    @staticmethod
    async def delete_role(session: AsyncSession, role_id: int) -> bool:
        """删除角色"""
        role = await AsyncPermissionMapper.get_role_by_id(session, role_id)
        if not role:
            raise ValueError(f"Role with id {role_id} not found")
        
        await AsyncDB.delete(session, role)
        await AsyncDB.commit(session)
        return True
    
    # Permission 相关方法
    @staticmethod
    async def get_permission_by_id(session: AsyncSession, permission_id: int) -> Optional[Permission]:
        """根据 ID 获取权限"""
        return await AsyncDB.get_by_id(session, Permission, permission_id)
    
    @staticmethod
    async def get_permission_by_code(session: AsyncSession, code: str) -> Optional[Permission]:
        """根据编码获取权限"""
        return await AsyncDB.get_by_field(session, Permission, "code", code)
    
    @staticmethod
    async def get_all_permissions(session: AsyncSession) -> List[Permission]:
        """获取所有权限"""
        stmt = select(Permission).order_by(Permission.resource, Permission.action)
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def create_permission(
        session: AsyncSession,
        name: str,
        code: str,
        description: Optional[str] = None,
        resource: Optional[str] = None,
        action: Optional[str] = None
    ) -> Permission:
        """创建权限"""
        # 检查编码是否已存在
        existing = await AsyncPermissionMapper.get_permission_by_code(session, code)
        if existing:
            raise ValueError(f"Permission code '{code}' already exists")
        
        permission = Permission(
            name=name,
            code=code,
            description=description,
            resource=resource,
            action=action
        )
        permission = await AsyncDB.create(session, permission)
        await AsyncDB.commit(session)
        return permission
    
    # RolePermission 相关方法
    @staticmethod
    async def assign_permission_to_role(
        session: AsyncSession,
        role_id: int,
        permission_id: int
    ) -> RolePermission:
        """为角色分配权限"""
        # 检查是否已存在
        stmt = select(RolePermission).where(
            and_(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id
            )
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            return existing
        
        rp = RolePermission(role_id=role_id, permission_id=permission_id)
        rp = await AsyncDB.create(session, rp)
        await AsyncDB.commit(session)
        return rp
    
    @staticmethod
    async def remove_permission_from_role(
        session: AsyncSession,
        role_id: int,
        permission_id: int
    ) -> bool:
        """移除角色的权限"""
        stmt = select(RolePermission).where(
            and_(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id
            )
        )
        result = await session.execute(stmt)
        rp = result.scalar_one_or_none()
        
        if not rp:
            raise ValueError("RolePermission not found")
        
        await AsyncDB.delete(session, rp)
        await AsyncDB.commit(session)
        return True
    
    @staticmethod
    async def revoke_permission_from_role(
        session: AsyncSession,
        role_id: int,
        permission_id: int
    ) -> bool:
        """撤销角色的权限"""
        stmt = select(RolePermission).where(
            and_(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id
            )
        )
        result = await session.execute(stmt)
        rp = result.scalar_one_or_none()
        
        if not rp:
            return False
        
        await AsyncDB.delete(session, rp)
        await AsyncDB.commit(session)
        return True
    
    @staticmethod
    async def get_role_permissions(
        session: AsyncSession,
        role_id: int
    ) -> List[Permission]:
        """获取角色的所有权限"""
        stmt = select(Permission).join(
            RolePermission,
            Permission.id == RolePermission.permission_id
        ).where(RolePermission.role_id == role_id)
        
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    # UserRole 相关方法
    @staticmethod
    async def assign_role_to_user(
        session: AsyncSession,
        user_id: int,
        role_id: int,
        organization_id: Optional[int] = None,
        scope: Optional[str] = None
    ) -> UserRole:
        """为用户分配角色"""
        # 检查是否已存在
        stmt = select(UserRole).where(
            and_(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
                UserRole.organization_id == organization_id
            )
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            existing.is_active = True
            await AsyncDB.commit(session)
            return existing
        
        ur = UserRole(
            user_id=user_id,
            role_id=role_id,
            organization_id=organization_id,
            scope=scope,
            is_active=True
        )
        ur = await AsyncDB.create(session, ur)
        await AsyncDB.commit(session)
        return ur
    
    @staticmethod
    async def revoke_role_from_user(
        session: AsyncSession,
        user_id: int,
        role_id: int,
        organization_id: Optional[int] = None
    ) -> bool:
        """撤销用户的角色"""
        stmt = select(UserRole).where(
            and_(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
                UserRole.organization_id == organization_id
            )
        )
        result = await session.execute(stmt)
        ur = result.scalar_one_or_none()
        
        if not ur:
            return False
        
        ur.is_active = False
        await AsyncDB.commit(session)
        return True
    
    @staticmethod
    async def get_user_roles_by_role(
        session: AsyncSession,
        role_id: int
    ) -> List[UserRole]:
        """根据角色ID获取所有用户角色关联"""
        stmt = select(UserRole).where(UserRole.role_id == role_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_user_roles(
        session: AsyncSession,
        user_id: int,
        organization_id: Optional[int] = None,
        include_inactive: bool = False
    ) -> List[UserRole]:
        """获取用户的所有角色"""
        stmt = select(UserRole).where(UserRole.user_id == user_id)
        
        if organization_id is not None:
            stmt = stmt.where(UserRole.organization_id == organization_id)
        
        if not include_inactive:
            stmt = stmt.where(UserRole.is_active == True)
        
        stmt = stmt.options(selectinload(UserRole.role))
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_user_permissions(
        session: AsyncSession,
        user_id: int,
        organization_id: Optional[int] = None
    ) -> Set[str]:
        """
        获取用户的所有权限（包括继承的权限）
        
        Returns:
            权限代码集合
        """
        # 获取用户的所有角色
        user_roles = await AsyncPermissionMapper.get_user_roles(
            session, user_id, organization_id
        )
        
        # 获取每个角色的权限
        permission_codes = set()
        for user_role in user_roles:
            role = user_role.role
            if not role:
                continue
            
            # 获取角色的权限
            permissions = await AsyncPermissionMapper.get_role_permissions(
                session, role.id
            )
            permission_codes.update([p.code for p in permissions])
        
        return permission_codes
    
    @staticmethod
    async def check_permission(
        session: AsyncSession,
        user_id: int,
        permission_code: str,
        organization_id: Optional[int] = None
    ) -> bool:
        """检查用户是否有指定权限"""
        permissions = await AsyncPermissionMapper.get_user_permissions(
            session, user_id, organization_id
        )
        return permission_code in permissions

