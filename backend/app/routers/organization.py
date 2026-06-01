"""
组织架构路由
"""
from fastapi import APIRouter, Depends, status, Form
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.utils.auth import get_current_user, require_any_permission, require_system_admin
from app.schemas.response import SuccessResponse
from app.models.user import User
from app.services.organization_service import AsyncOrganizationService
from app.utils.logger_config import get_logger
from app.utils.error_handler import ValidationError

logger = get_logger(__name__)
router = APIRouter()


@router.get(
    "/schools",
    response_model=SuccessResponse[List[dict]],
    summary="获取学校列表（公开接口，注册用）"
)
async def get_schools(
    db: AsyncSession = Depends(get_async_db)
):
    """获取所有学校列表，无需认证"""
    result = await AsyncOrganizationService.get_schools(db)
    return SuccessResponse(message="查询成功", data=result)


@router.get(
    "/{school_id}/departments",
    response_model=SuccessResponse[List[dict]],
    summary="获取学校下的学院/部门列表（公开接口，注册用）"
)
async def get_departments(
    school_id: int,
    db: AsyncSession = Depends(get_async_db)
):
    """获取学校下的学院/部门，无需认证"""
    result = await AsyncOrganizationService.get_departments_for_register(db, school_id)
    return SuccessResponse(message="查询成功", data=result)


@router.get(
    "/{college_id}/majors",
    response_model=SuccessResponse[List[dict]],
    summary="获取学院下的专业列表（公开接口，注册用）"
)
async def get_majors(
    college_id: int,
    db: AsyncSession = Depends(get_async_db)
):
    """获取学院下的专业列表，无需认证"""
    result = await AsyncOrganizationService.get_majors_for_register(db, college_id)
    return SuccessResponse(message="查询成功", data=result)


@router.get(
    "/{major_id}/grade-distribution",
    response_model=SuccessResponse[List[dict]],
    summary="获取专业下的年级分布"
)
async def get_grade_distribution(
    major_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取某专业下各年级的学生人数分布"""
    result = await AsyncOrganizationService.get_major_grade_distribution(db, major_id)
    return SuccessResponse(message="查询成功", data=result)


@router.post(
    "/create",
    response_model=SuccessResponse[dict],
    status_code=status.HTTP_201_CREATED,
    summary="创建组织"
)
async def create_organization(
    name: str = Form(...),
    code: str = Form(...),
    org_type: str = Form(...),
    parent_id: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    school_id: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """创建组织节点"""
    if parent_id is None:
        await require_system_admin(db, current_user)
    else:
        await require_any_permission(
            db,
            current_user,
            ["organization:write", "organization:manage"],
            organization_id=parent_id,
        )
    if not name or not code or not org_type:
        raise ValidationError("组织名称、编码和类型不能为空")
    
    result = await AsyncOrganizationService.create_organization(
        db,
        name=name,
        code=code,
        org_type=org_type,
        parent_id=parent_id,
        description=description,
        school_id=school_id
    )
    return SuccessResponse(message="创建成功", data=result)


@router.get(
    "/{organization_id}",
    response_model=SuccessResponse[dict],
    summary="获取组织详情"
)
async def get_organization(
    organization_id: int,
    include_children: bool = False,
    include_members: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取组织详情"""
    await require_any_permission(
        db,
        current_user,
        ["organization:read", "organization:write", "organization:manage"],
        organization_id=organization_id,
    )
    result = await AsyncOrganizationService.get_organization(
        db, organization_id, include_children, include_members
    )
    return SuccessResponse(message="查询成功", data=result)


@router.put(
    "/{organization_id}",
    response_model=SuccessResponse[dict],
    summary="更新组织"
)
async def update_organization(
    organization_id: int,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """更新组织信息"""
    await require_any_permission(
        db,
        current_user,
        ["organization:write", "organization:manage"],
        organization_id=organization_id,
    )
    result = await AsyncOrganizationService.update_organization(
        db, organization_id, name, description, status
    )
    return SuccessResponse(message="更新成功", data=result)


@router.delete(
    "/{organization_id}",
    response_model=SuccessResponse[dict],
    summary="删除组织"
)
async def delete_organization(
    organization_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """删除组织"""
    await require_any_permission(
        db,
        current_user,
        ["organization:write", "organization:delete", "organization:manage"],
        organization_id=organization_id,
    )
    result = await AsyncOrganizationService.delete_organization(db, organization_id)
    return SuccessResponse(message="删除成功", data={"deleted": result})


@router.get(
    "/{organization_id}/children",
    response_model=SuccessResponse[List[dict]],
    summary="获取子组织列表"
)
async def get_children(
    organization_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取子组织列表"""
    await require_any_permission(
        db,
        current_user,
        ["organization:read", "organization:write", "organization:manage"],
        organization_id=organization_id,
    )
    result = await AsyncOrganizationService.get_children(db, organization_id)
    return SuccessResponse(message="查询成功", data=result)


@router.get(
    "/{organization_id}/tree",
    response_model=SuccessResponse[dict],
    summary="获取组织树"
)
async def get_tree(
    organization_id: int,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取组织树"""
    await require_any_permission(
        db,
        current_user,
        ["organization:read", "organization:write", "organization:manage"],
        organization_id=organization_id,
    )
    result = await AsyncOrganizationService.get_tree(db, organization_id, include_inactive)
    return SuccessResponse(message="查询成功", data=result)


@router.get(
    "/{organization_id}/path",
    response_model=SuccessResponse[List[dict]],
    summary="获取组织路径"
)
async def get_path(
    organization_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取组织路径（向上查找）"""
    await require_any_permission(
        db,
        current_user,
        ["organization:read", "organization:write", "organization:manage"],
        organization_id=organization_id,
    )
    result = await AsyncOrganizationService.get_path(db, organization_id)
    return SuccessResponse(message="查询成功", data=result)


@router.post(
    "/{organization_id}/member",
    response_model=SuccessResponse[dict],
    summary="添加组织成员"
)
async def add_member(
    organization_id: int,
    user_id: int = Form(...),
    role: str = Form("member"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """添加组织成员"""
    await require_any_permission(
        db,
        current_user,
        ["organization:write", "organization:manage", "user:write", "user:manage"],
        organization_id=organization_id,
    )
    result = await AsyncOrganizationService.add_member(
        db, user_id, organization_id, role
    )
    return SuccessResponse(message="添加成功", data=result)


@router.delete(
    "/{organization_id}/member/{user_id}",
    response_model=SuccessResponse[dict],
    summary="移除组织成员"
)
async def remove_member(
    organization_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """移除组织成员"""
    await require_any_permission(
        db,
        current_user,
        ["organization:write", "organization:manage", "user:write", "user:manage"],
        organization_id=organization_id,
    )
    result = await AsyncOrganizationService.remove_member(db, user_id, organization_id)
    return SuccessResponse(message="移除成功", data={"removed": result})


@router.get(
    "/{organization_id}/members",
    response_model=SuccessResponse[List[dict]],
    summary="获取组织成员列表"
)
async def get_members(
    organization_id: int,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取组织成员列表"""
    await require_any_permission(
        db,
        current_user,
        ["organization:read", "organization:write", "organization:manage"],
        organization_id=organization_id,
    )
    result = await AsyncOrganizationService.get_members(
        db, organization_id, include_inactive
    )
    return SuccessResponse(message="查询成功", data=result)


@router.get(
    "/user/{user_id}/organizations",
    response_model=SuccessResponse[List[dict]],
    summary="获取用户所属的所有组织"
)
async def get_user_organizations(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取用户所属的所有组织"""
    if user_id != current_user.id:
        await require_any_permission(
            db,
            current_user,
            ["organization:read", "organization:write", "organization:manage", "user:read", "user:manage"],
        )
    result = await AsyncOrganizationService.get_user_organizations(db, user_id)
    return SuccessResponse(message="查询成功", data=result)
