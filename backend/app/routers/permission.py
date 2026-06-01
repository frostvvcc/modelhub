"""
权限管理路由
"""
from fastapi import APIRouter, Depends, status, Form
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.utils.auth import get_current_user, is_system_admin, require_any_permission, require_system_admin
from app.schemas.response import SuccessResponse
from app.models.user import User
from app.services.permission_service import AsyncPermissionService
from app.utils.logger_config import get_logger
from app.utils.error_handler import ValidationError

logger = get_logger(__name__)
router = APIRouter()


@router.post(
    "/check",
    response_model=SuccessResponse[dict],
    summary="检查用户权限"
)
async def check_permission(
    permission_code: str = Form(...),
    organization_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """检查用户是否有指定权限"""
    # 验证权限代码不为空
    if not permission_code or not permission_code.strip():
        logger.warning(f"权限检查失败：权限代码为空 (user_id={current_user.id})")
        return SuccessResponse(
            message="权限代码不能为空",
            data={"has_permission": False, "permission_code": None}
        )
    
    permission_code = permission_code.strip()
    
    # 转换 organization_id 为整数（如果提供）
    org_id = None
    if organization_id:
        try:
            org_id = int(organization_id)
        except (ValueError, TypeError):
            logger.warning(f"权限检查失败：无效的 organization_id (user_id={current_user.id}, org_id={organization_id})")
            org_id = None
    
    has_permission = await AsyncPermissionService.check_permission(
        db, current_user.id, permission_code, org_id
    )
    return SuccessResponse(
        message="权限检查完成",
        data={"has_permission": has_permission, "permission_code": permission_code}
    )


@router.get(
    "/user/{user_id}/permissions",
    response_model=SuccessResponse[List[str]],
    summary="获取用户所有权限"
)
async def get_user_permissions(
    user_id: int,
    organization_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取用户的所有权限（包括继承的权限）"""
    if user_id != current_user.id:
        await require_any_permission(
            db,
            current_user,
            ["permission:read", "permission:write", "permission:manage"],
        )
    permissions = await AsyncPermissionService.get_user_permissions(
        db, user_id, organization_id
    )
    return SuccessResponse(message="查询成功", data=permissions)


@router.get(
    "/user/{user_id}/roles",
    response_model=SuccessResponse[List[dict]],
    summary="获取用户所有角色"
)
async def get_user_roles(
    user_id: int,
    organization_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取用户的所有角色"""
    if user_id != current_user.id:
        await require_any_permission(
            db,
            current_user,
            ["permission:read", "permission:write", "permission:manage"],
        )
    roles = await AsyncPermissionService.get_user_roles(
        db, user_id, organization_id
    )
    return SuccessResponse(message="查询成功", data=roles)


@router.post(
    "/role",
    response_model=SuccessResponse[dict],
    status_code=status.HTTP_201_CREATED,
    summary="创建角色"
)
async def create_role(
    name: str = Form(...),
    code: str = Form(...),
    description: Optional[str] = Form(None),
    level: str = Form("class"),
    is_system: bool = Form(False),
    school_id: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """创建角色"""
    await require_system_admin(db, current_user)
    if not name or not code:
        raise ValidationError("角色名称和代码不能为空")
    
    result = await AsyncPermissionService.create_role(
        db,
        name=name,
        code=code,
        description=description,
        level=level,
        is_system=is_system,
        school_id=school_id
    )
    return SuccessResponse(message="创建成功", data=result)


@router.get(
    "/roles",
    response_model=SuccessResponse[List[dict]],
    summary="获取角色列表"
)
async def get_roles(
    school_id: Optional[int] = None,
    include_system: bool = True,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取角色列表"""
    await require_any_permission(
        db,
        current_user,
        ["permission:read", "permission:write", "permission:manage"],
    )
    if not await is_system_admin(db, current_user):
        school_id = school_id or current_user.school_id
        include_system = False
    result = await AsyncPermissionService.get_roles(
        db, school_id, include_system
    )
    return SuccessResponse(message="查询成功", data=result)


@router.get(
    "/permissions",
    response_model=SuccessResponse[List[dict]],
    summary="获取所有权限"
)
async def get_all_permissions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取所有权限"""
    await require_any_permission(
        db,
        current_user,
        ["permission:read", "permission:write", "permission:manage"],
    )
    result = await AsyncPermissionService.get_all_permissions(db)
    return SuccessResponse(message="查询成功", data=result)


@router.get(
    "/role/{role_id}/permissions",
    response_model=SuccessResponse[List[dict]],
    summary="获取角色的所有权限"
)
async def get_role_permissions(
    role_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取角色的所有权限"""
    await require_any_permission(
        db,
        current_user,
        ["permission:read", "permission:write", "permission:manage"],
    )
    result = await AsyncPermissionService.get_role_permissions(db, role_id)
    return SuccessResponse(message="查询成功", data=result)


@router.put(
    "/role/{role_id}",
    response_model=SuccessResponse[dict],
    summary="更新角色"
)
async def update_role(
    role_id: int,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    level: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """更新角色信息"""
    await require_system_admin(db, current_user)
    result = await AsyncPermissionService.update_role(
        db, role_id, name=name, description=description, level=level
    )
    return SuccessResponse(message="更新成功", data=result)


@router.delete(
    "/role/{role_id}",
    response_model=SuccessResponse[dict],
    summary="删除角色"
)
async def delete_role(
    role_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """删除角色"""
    await require_system_admin(db, current_user)
    result = await AsyncPermissionService.delete_role(db, role_id)
    return SuccessResponse(message="删除成功", data=result)


@router.post(
    "/role/{role_id}/permission",
    response_model=SuccessResponse[dict],
    summary="为角色分配权限"
)
async def assign_permission_to_role(
    role_id: int,
    permission_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """为角色分配权限"""
    await require_system_admin(db, current_user)
    result = await AsyncPermissionService.assign_permission_to_role(
        db, role_id, permission_id
    )
    return SuccessResponse(message="分配成功", data=result)


@router.delete(
    "/role/{role_id}/permission/{permission_id}",
    response_model=SuccessResponse[dict],
    summary="移除角色权限"
)
async def remove_permission_from_role(
    role_id: int,
    permission_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """移除角色的权限"""
    await require_system_admin(db, current_user)
    result = await AsyncPermissionService.remove_permission_from_role(
        db, role_id, permission_id
    )
    return SuccessResponse(message="移除成功", data=result)


@router.post(
    "/user/{user_id}/role",
    response_model=SuccessResponse[dict],
    summary="为用户分配角色"
)
async def assign_role_to_user(
    user_id: int,
    role_id: int = Form(...),
    organization_id: Optional[int] = Form(None),
    scope: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """为用户分配角色"""
    await require_system_admin(db, current_user)
    result = await AsyncPermissionService.assign_role_to_user(
        db, user_id, role_id, organization_id, scope
    )
    return SuccessResponse(message="分配成功", data=result)


@router.post(
    "/organization/{organization_id}/access",
    response_model=SuccessResponse[dict],
    summary="检查组织访问权限"
)
async def check_organization_access(
    organization_id: int,
    permission_code: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """检查用户对组织的访问权限"""
    has_access = await AsyncPermissionService.check_organization_access(
        db, current_user.id, organization_id, permission_code
    )
    return SuccessResponse(
        message="权限检查完成",
        data={"has_access": has_access, "permission_code": permission_code}
    )
