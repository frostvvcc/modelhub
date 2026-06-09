"""
用户路由
"""
from fastapi import APIRouter, Depends, status, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import os

from app.database_async import get_async_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.auth import get_current_user, create_access_token, require_system_admin
from app.schemas.user import RegisterRequest, LoginRequest, UserInfoResponse, TokenResponse, UpdateProfileRequest, ChangePasswordRequest
from app.schemas.response import SuccessResponse
from app.models.user import User
from app.services.user_service import AsyncUserService
from app.utils.file_utils import save_uploaded_file
from app.utils.async_adapter import AsyncService
from app.config import settings
from app.utils.logger_config import get_logger
from app.utils.error_handler import NotFoundError, ValidationError, ForbiddenError

logger = get_logger(__name__)
router = APIRouter()


@router.post(
    "/register",
    response_model=SuccessResponse[TokenResponse],
    status_code=status.HTTP_201_CREATED,
    summary="用户注册",
    description="注册新用户账户"
)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """用户注册"""
    # 使用异步 Service，异常由中间件统一处理
    result = await AsyncUserService.register(
        db,
        request.name,
        request.password,
        email=request.email,
        describe=request.describe,
        school_id=request.school_id,
        student_id=request.student_id,
        employee_id=request.employee_id,
        role=request.role,
        organization_id=request.organization_id,
    )
    return SuccessResponse(
        message="注册成功",
        data=TokenResponse(token=result["token"])
    )


@router.post(
    "/login",
    response_model=SuccessResponse[dict],
    summary="用户登录",
    description="用户登录获取访问令牌"
)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """用户登录"""
    # 使用异步 Service，异常由中间件统一处理
    user = await AsyncUserService.login(db, request.account, request.password)
    return SuccessResponse(message="登录成功", data=user)


@router.get(
    "/info",
    response_model=SuccessResponse[dict],
    summary="获取用户信息",
    description="获取当前登录用户的详细信息"
)
async def get_user_info(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取当前登录用户的信息"""
    # 异常由中间件统一处理
    user = await AsyncUserService.get_user_detail(db, current_user.id)
    return SuccessResponse(message="获取成功", data=user)


@router.get(
    "/test",
    summary="测试接口",
    description="测试认证是否正常工作"
)
async def test(
    current_user: User = Depends(get_current_user)
):
    """测试接口，验证 JWT 认证"""
    return SuccessResponse(
        message="测试成功",
        data=current_user.to_dict()
    )


@router.put(
    "/profile",
    response_model=SuccessResponse[dict],
    summary="更新个人资料",
    description="更新当前用户的个人资料信息"
)
async def update_profile(
    request: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """更新个人资料"""
    result = await AsyncUserService.update_profile(
        db,
        current_user.id,
        name=request.name,
        describe=request.describe,
        phone=request.phone,
        student_id=request.student_id,
        employee_id=request.employee_id,
    )
    return SuccessResponse(message="资料更新成功", data=result)


@router.put(
    "/password",
    response_model=SuccessResponse[dict],
    summary="修改密码",
    description="修改当前用户的登录密码"
)
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """修改密码"""
    await AsyncUserService.change_password(
        db,
        current_user.id,
        request.old_password,
        request.new_password,
    )
    return SuccessResponse(message="密码修改成功", data={})


@router.get(
    "/enterprise",
    response_model=SuccessResponse[list],
    summary="获取企业用户列表",
    description="获取所有企业用户"
)
async def get_enterprise_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取企业用户列表"""
    # 异常由中间件统一处理
    users = await AsyncUserService.get_enterprise_users(db)
    return SuccessResponse(message="获取配置商成功", data=users)


@router.get(
    "/admin/users",
    response_model=SuccessResponse[list],
    summary="管理员搜索用户列表",
)
async def admin_search_users(
    keyword: str = "",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """管理员搜索用户（按邮箱或姓名），需要管理员权限"""
    await require_system_admin(db, current_user)
    users = await AsyncUserService.search_users(db, keyword)
    return SuccessResponse(message="查询成功", data=users)


@router.put(
    "/admin/users/{user_id}/role",
    response_model=SuccessResponse[dict],
    summary="管理员修改用户角色",
)
async def admin_update_user_role(
    user_id: int,
    role: str = "student",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """管理员修改用户角色（admin/teacher/student）"""
    await require_system_admin(db, current_user)
    result = await AsyncUserService.update_user_role(db, user_id, role)
    return SuccessResponse(message="角色更新成功", data=result)


@router.get(
    "/avatar/{filename:path}",
    summary="获取用户头像",
    description="根据文件名获取用户头像",
    response_class=FileResponse
)
async def get_avatar(filename: str):
    """获取用户头像文件"""
    from app.utils.error_handler import ForbiddenError, NotFoundError
    
    uploads_dir = settings.uploads_dir
    
    # 安全检查：防止路径遍历攻击
    safe_path = os.path.normpath(os.path.join(str(uploads_dir), filename))
    if not safe_path.startswith(os.path.normpath(str(uploads_dir))):
        raise ForbiddenError("非法路径访问")
    
    # 检查文件是否存在
    if not os.path.isfile(safe_path):
        # 返回默认头像
        default_avatar = os.path.join(str(uploads_dir), 'image.png')
        if os.path.isfile(default_avatar):
            return FileResponse(
                default_avatar,
                media_type="image/png",
                headers={"X-Content-Type-Options": "nosniff"}
            )
        raise NotFoundError("头像文件不存在")
    
    # 返回头像文件
    return FileResponse(
        safe_path,
        media_type="image/png",
        headers={"X-Content-Type-Options": "nosniff"}
    )


@router.put(
    "/avatar",
    summary="更新用户头像",
    description="上传并更新用户头像"
)
async def update_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """更新用户头像"""
    from app.utils.error_handler import ValidationError, InternalServerError
    import uuid

    if not file:
        raise ValidationError("请上传文件")

    file_content = await file.read()
    if not file_content:
        raise ValidationError("文件内容为空")

    ext = os.path.splitext(file.filename or "upload.png")[1] or ".png"
    filename = f"avatar_{current_user.id}_{uuid.uuid4().hex[:8]}{ext}"
    save_path = os.path.join(str(settings.uploads_dir), filename)

    def _write_bytes():
        with open(save_path, "wb") as f:
            f.write(file_content)
        return filename

    saved_name = await AsyncService.run_sync(_write_bytes)
    if not saved_name:
        raise InternalServerError("文件保存失败")

    avatar = await AsyncUserService.update_avatar(db, current_user.id, saved_name)
    return SuccessResponse(message="更新成功", data=avatar)

