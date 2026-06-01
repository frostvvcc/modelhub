"""
教学空间路由
"""
from fastapi import APIRouter, Depends, status, Form
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.utils.auth import get_current_user
from app.schemas.response import SuccessResponse
from app.models.user import User
from app.services.teaching_space_service import AsyncTeachingSpaceService
from app.utils.logger_config import get_logger
from app.utils.error_handler import ForbiddenError

logger = get_logger(__name__)
router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_space(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """创建教学空间（仅老师）"""
    if current_user.role not in ("teacher", "admin"):
        raise ForbiddenError("仅教师可创建教学空间")
    result = await AsyncTeachingSpaceService.create_space(db, current_user, name, description)
    return SuccessResponse(message="创建成功", data=result)


@router.get("")
async def list_spaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取教学空间列表（老师获取自己的，学生获取所在的）"""
    if current_user.role in ("teacher", "admin"):
        result = await AsyncTeachingSpaceService.list_spaces_for_teacher(db, current_user.id)
    else:
        result = await AsyncTeachingSpaceService.list_spaces_for_student(db, current_user.id)
    return SuccessResponse(message="查询成功", data=result)


@router.get("/admin/all")
async def list_all_spaces(
    organization_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """管理员获取所有教学空间（可按学院筛选）"""
    if current_user.role not in ("admin",):
        raise ForbiddenError("仅管理员可访问")
    result = await AsyncTeachingSpaceService.list_all_spaces(
        db, school_id=current_user.school_id, organization_id=organization_id
    )
    return SuccessResponse(message="查询成功", data=result)


@router.get("/by-major/{major_id}")
async def get_spaces_by_major(
    major_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取某个专业绑定的所有教学空间"""
    result = await AsyncTeachingSpaceService.get_spaces_by_major(db, major_id)
    return SuccessResponse(message="查询成功", data=result)


@router.get("/{space_id}")
async def get_space(
    space_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取教学空间详情"""
    result = await AsyncTeachingSpaceService.get_space(db, space_id)
    return SuccessResponse(message="查询成功", data=result)


@router.put("/{space_id}")
async def update_space(
    space_id: int,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    space_status: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """更新教学空间"""
    result = await AsyncTeachingSpaceService.update_space(
        db, space_id, current_user.id, name, description, space_status, user_role=current_user.role
    )
    return SuccessResponse(message="更新成功", data=result)


@router.delete("/{space_id}", status_code=status.HTTP_200_OK)
async def delete_space(
    space_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """删除教学空间"""
    await AsyncTeachingSpaceService.delete_space(db, space_id, current_user.id, user_role=current_user.role)
    return SuccessResponse(message="删除成功", data={"deleted": True})


@router.post("/{space_id}/bindMajor")
async def bind_major(
    space_id: int,
    major_id: int = Form(...),
    enrollment_year: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """绑定专业到教学空间（可指定年级）"""
    result = await AsyncTeachingSpaceService.bind_major(
        db, space_id, major_id, current_user.id,
        user_role=current_user.role, enrollment_year=enrollment_year
    )
    return SuccessResponse(message="绑定成功", data=result)


@router.delete("/{space_id}/unbindMajor/{major_id}")
async def unbind_major(
    space_id: int,
    major_id: int,
    enrollment_year: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """解绑专业（可指定年级）"""
    await AsyncTeachingSpaceService.unbind_major(
        db, space_id, major_id, current_user.id,
        user_role=current_user.role, enrollment_year=enrollment_year
    )
    return SuccessResponse(message="解绑成功", data={"unbound": True})


@router.get("/{space_id}/majors")
async def get_majors(
    space_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取空间绑定的专业列表"""
    result = await AsyncTeachingSpaceService.get_bound_majors(db, space_id)
    return SuccessResponse(message="查询成功", data=result)


@router.get("/{space_id}/students")
async def get_students(
    space_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取空间内学生列表"""
    result = await AsyncTeachingSpaceService.get_space_students(db, space_id)
    return SuccessResponse(message="查询成功", data=result)


@router.post("/{space_id}/students")
async def add_student(
    space_id: int,
    student_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """添加学生到教学空间"""
    if current_user.role not in ("teacher", "admin"):
        raise ForbiddenError("仅教师或管理员可操作")
    result = await AsyncTeachingSpaceService.add_student(db, space_id, student_id, current_user.id, user_role=current_user.role)
    return SuccessResponse(message="添加成功", data=result)


@router.delete("/{space_id}/students/{student_id}")
async def remove_student(
    space_id: int,
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """从教学空间移除学生"""
    if current_user.role not in ("teacher", "admin"):
        raise ForbiddenError("仅教师或管理员可操作")
    await AsyncTeachingSpaceService.remove_student(db, space_id, student_id, current_user.id, user_role=current_user.role)
    return SuccessResponse(message="移除成功", data={"removed": True})


@router.post("/{space_id}/publish")
async def publish_resource(
    space_id: int,
    resource_type: str = Form(...),
    resource_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """分发资源到教学空间"""
    result = await AsyncTeachingSpaceService.publish_resource(
        db, space_id, current_user.id, resource_type, resource_id, user_role=current_user.role
    )
    return SuccessResponse(message="分发成功", data=result)


@router.delete("/{space_id}/unpublish")
async def unpublish_resource(
    space_id: int,
    resource_type: str = Form(...),
    resource_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """撤回资源分发"""
    await AsyncTeachingSpaceService.unpublish_resource(
        db, space_id, current_user.id, resource_type, resource_id, user_role=current_user.role
    )
    return SuccessResponse(message="撤回成功", data={"unpublished": True})


@router.get("/{space_id}/resources")
async def get_resources(
    space_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取空间内的资源列表"""
    if current_user.role == "student":
        result = await AsyncTeachingSpaceService.get_student_space_resources(db, current_user.id, space_id)
    else:
        result = await AsyncTeachingSpaceService.get_space_resources(db, space_id)
    return SuccessResponse(message="查询成功", data=result)
