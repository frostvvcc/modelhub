"""
异步权限管理 Service
处理权限管理相关的业务逻辑，支持层级权限继承
"""
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any, Set
from app.mappers.permission_mapper import AsyncPermissionMapper
from app.mappers.organization_mapper import AsyncOrganizationMapper
from app.models.permission import Role, Permission, UserRole
from app.utils.logger_config import get_logger
from app.utils.cache import cache_result, clear_cache
from app.utils.error_handler import (
    NotFoundError,
    ValidationError,
    InternalServerError
)

logger = get_logger(__name__)


class AsyncPermissionService:
    """异步权限管理服务类"""
    
    @staticmethod
    @cache_result(ttl=300, key_prefix="permission")  # 缓存5分钟
    async def check_permission(
        session: AsyncSession,
        user_id: int,
        permission_code: str,
        organization_id: Optional[int] = None
    ) -> bool:
        """
        检查用户是否有指定权限（支持层级继承）

        Args:
            session: 数据库会话
            user_id: 用户ID
            permission_code: 权限代码
            organization_id: 组织ID（可选，用于组织级权限检查）

        Returns:
            是否有权限
        """
        logger.debug(f"检查权限: user_id={user_id}, permission={permission_code}, org_id={organization_id}")

        # 始终先检查全局权限（organization_id=None 的角色分配）
        has_permission = await AsyncPermissionMapper.check_permission(
            session, user_id, permission_code, None
        )
        if has_permission:
            return True

        # 检查指定组织的直接权限
        if organization_id:
            has_permission = await AsyncPermissionMapper.check_permission(
                session, user_id, permission_code, organization_id
            )
            if has_permission:
                return True

            # 检查上级组织的权限继承
            path = await AsyncOrganizationMapper.get_path(session, organization_id)
            for org in reversed(path):  # 从根到当前
                has_permission = await AsyncPermissionMapper.check_permission(
                    session, user_id, permission_code, org.id
                )
                if has_permission:
                    return True

        return False
    
    @staticmethod
    async def get_user_permissions(
        session: AsyncSession,
        user_id: int,
        organization_id: Optional[int] = None
    ) -> List[str]:
        """
        获取用户的所有权限（包括继承的权限）

        Args:
            session: 数据库会话
            user_id: 用户ID
            organization_id: 组织ID（可选）

        Returns:
            权限代码列表
        """
        logger.debug(f"获取用户权限: user_id={user_id}, org_id={organization_id}")

        # 始终获取全局权限（organization_id=None 的角色分配）
        permissions = await AsyncPermissionMapper.get_user_permissions(
            session, user_id, None
        )

        # 如果指定了组织，还要获取该组织及其上级组织的权限
        if organization_id:
            org_permissions = await AsyncPermissionMapper.get_user_permissions(
                session, user_id, organization_id
            )
            permissions.update(org_permissions)

            path = await AsyncOrganizationMapper.get_path(session, organization_id)
            for org in path:
                org_permissions = await AsyncPermissionMapper.get_user_permissions(
                    session, user_id, org.id
                )
                permissions.update(org_permissions)

        return sorted(list(permissions))
    
    @staticmethod
    async def get_user_roles(
        session: AsyncSession,
        user_id: int,
        organization_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """获取用户的所有角色"""
        logger.debug(f"获取用户角色: user_id={user_id}, org_id={organization_id}")
        
        user_roles = await AsyncPermissionMapper.get_user_roles(
            session, user_id, organization_id
        )
        
        return [ur.to_dict() for ur in user_roles]
    
    @staticmethod
    async def create_role(
        session: AsyncSession,
        name: str,
        code: str,
        description: Optional[str] = None,
        level: str = "class",
        is_system: bool = False,
        school_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """创建角色"""
        logger.info(f"创建角色: name={name}, code={code}, level={level}")
        
        try:
            # 验证级别
            valid_levels = ['system', 'school', 'college', 'major', 'department', 'class']
            if level not in valid_levels:
                raise ValidationError(f"无效的权限级别: {level}")
            
            role = await AsyncPermissionMapper.create_role(
                session=session,
                name=name,
                code=code,
                description=description,
                level=level,
                is_system=is_system,
                school_id=school_id
            )
            
            logger.info(f"成功创建角色: id={role.id}")
            return role.to_dict()
            
        except ValueError as e:
            logger.warning(f"创建角色失败: {str(e)}")
            raise ValidationError(str(e))
        except Exception as e:
            logger.error(f"创建角色失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"创建角色失败: {str(e)}")
    
    @staticmethod
    async def assign_permission_to_role(
        session: AsyncSession,
        role_id: int,
        permission_id: int
    ) -> Dict[str, Any]:
        """为角色分配权限"""
        logger.info(f"为角色分配权限: role_id={role_id}, permission_id={permission_id}")
        
        # 验证角色和权限是否存在
        role = await AsyncPermissionMapper.get_role_by_id(session, role_id)
        if not role:
            raise NotFoundError("角色不存在")
        
        permission = await AsyncPermissionMapper.get_permission_by_id(session, permission_id)
        if not permission:
            raise NotFoundError("权限不存在")
        
        rp = await AsyncPermissionMapper.assign_permission_to_role(
            session, role_id, permission_id
        )
        
        logger.info(f"成功为角色分配权限")
        # 清除权限缓存
        clear_cache("permission:*")
        return rp.to_dict()
    
    @staticmethod
    async def assign_role_to_user(
        session: AsyncSession,
        user_id: int,
        role_id: int,
        organization_id: Optional[int] = None,
        scope: Optional[str] = None
    ) -> Dict[str, Any]:
        """为用户分配角色"""
        logger.info(f"为用户分配角色: user_id={user_id}, role_id={role_id}, org_id={organization_id}")
        
        # 验证角色是否存在
        role = await AsyncPermissionMapper.get_role_by_id(session, role_id)
        if not role:
            raise NotFoundError("角色不存在")
        
        # 如果指定了组织，验证组织是否存在
        if organization_id:
            org = await AsyncOrganizationMapper.get_organization_by_id(session, organization_id)
            if not org:
                raise NotFoundError("组织不存在")
        
        ur = await AsyncPermissionMapper.assign_role_to_user(
            session, user_id, role_id, organization_id, scope
        )
        
        logger.info(f"成功为用户分配角色")
        # 清除权限缓存
        clear_cache(f"permission:*:{user_id}:*")
        return ur.to_dict()
    
    @staticmethod
    async def get_roles(
        session: AsyncSession,
        school_id: Optional[int] = None,
        include_system: bool = True
    ) -> List[Dict[str, Any]]:
        """获取角色列表"""
        logger.debug(f"获取角色列表: school_id={school_id}, include_system={include_system}")
        
        roles = await AsyncPermissionMapper.get_roles(
            session, school_id, include_system
        )
        
        return [role.to_dict() for role in roles]
    
    @staticmethod
    async def get_all_permissions(session: AsyncSession) -> List[Dict[str, Any]]:
        """获取所有权限"""
        logger.debug("获取所有权限列表")
        
        permissions = await AsyncPermissionMapper.get_all_permissions(session)
        return [p.to_dict() for p in permissions]
    
    @staticmethod
    async def get_role_permissions(
        session: AsyncSession,
        role_id: int
    ) -> List[Dict[str, Any]]:
        """获取角色的所有权限"""
        logger.debug(f"获取角色权限: role_id={role_id}")
        
        permissions = await AsyncPermissionMapper.get_role_permissions(session, role_id)
        return [p.to_dict() for p in permissions]
    
    @staticmethod
    async def update_role(
        session: AsyncSession,
        role_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        level: Optional[str] = None
    ) -> Dict[str, Any]:
        """更新角色信息"""
        logger.debug(f"更新角色: role_id={role_id}")
        
        role = await AsyncPermissionMapper.get_role_by_id(session, role_id)
        if not role:
            raise NotFoundError("角色不存在")
        
        if role.is_system:
            raise ValidationError("系统角色不能修改")
        
        update_data = {}
        if name is not None:
            update_data['name'] = name
        if description is not None:
            update_data['description'] = description
        if level is not None:
            update_data['level'] = level
        
        role = await AsyncPermissionMapper.update_role(session, role_id, **update_data)
        logger.info(f"成功更新角色: role_id={role_id}")
        return role.to_dict()
    
    @staticmethod
    async def delete_role(
        session: AsyncSession,
        role_id: int
    ) -> Dict[str, Any]:
        """删除角色"""
        logger.debug(f"删除角色: role_id={role_id}")
        
        role = await AsyncPermissionMapper.get_role_by_id(session, role_id)
        if not role:
            raise NotFoundError("角色不存在")
        
        if role.is_system:
            raise ValidationError("系统角色不能删除")
        
        # 检查是否有用户使用此角色
        user_roles = await AsyncPermissionMapper.get_user_roles_by_role(session, role_id)
        if user_roles:
            raise ValidationError("该角色正在被使用，无法删除")
        
        await AsyncPermissionMapper.delete_role(session, role_id)
        logger.info(f"成功删除角色: role_id={role_id}")
        return {"id": role_id, "deleted": True}
    
    @staticmethod
    async def remove_permission_from_role(
        session: AsyncSession,
        role_id: int,
        permission_id: int
    ) -> Dict[str, Any]:
        """移除角色的权限"""
        logger.debug(f"移除角色权限: role_id={role_id}, permission_id={permission_id}")
        
        role = await AsyncPermissionMapper.get_role_by_id(session, role_id)
        if not role:
            raise NotFoundError("角色不存在")
        
        result = await AsyncPermissionMapper.revoke_permission_from_role(session, role_id, permission_id)
        if not result:
            raise NotFoundError("权限关联不存在")
        
        logger.info(f"成功移除角色权限")
        return {"role_id": role_id, "permission_id": permission_id, "removed": True}
    
    @staticmethod
    async def check_organization_access(
        session: AsyncSession,
        user_id: int,
        organization_id: int,
        permission_code: str
    ) -> bool:
        """
        检查用户对组织的访问权限
        
        Args:
            session: 数据库会话
            user_id: 用户ID
            organization_id: 组织ID
            permission_code: 权限代码
        
        Returns:
            是否有权限
        """
        logger.debug(f"检查组织访问权限: user_id={user_id}, org_id={organization_id}, permission={permission_code}")
        
        # 首先检查用户是否在组织中
        is_member = await AsyncOrganizationMapper.check_user_in_organization(
            session, user_id, organization_id
        )
        
        if not is_member:
            # 检查是否有系统级权限
            return await AsyncPermissionService.check_permission(
                session, user_id, permission_code, None
            )
        
        # 检查权限
        return await AsyncPermissionService.check_permission(
            session, user_id, permission_code, organization_id
        )

