"""
FastAPI 认证工具
JWT Token 认证和密码加密
"""
from datetime import datetime, timedelta
from typing import Optional, Iterable
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.database_async import get_async_db
from app.config import settings
from app.models.user import User
from app.utils.async_db import AsyncDB
from app.mappers.organization_mapper import AsyncOrganizationMapper
from app.services.permission_service import AsyncPermissionService
from app.utils.error_handler import ForbiddenError
from functools import wraps
from typing import Callable, Any, Optional
import logging

logger = logging.getLogger(__name__)

# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer Token 安全方案
security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    创建 JWT Token
    
    Args:
        data: 要编码的数据（通常是用户信息）
        expires_delta: 过期时间增量
    
    Returns:
        JWT Token 字符串
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.access_token_expire_minutes
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.secret_key,
        algorithm=settings.algorithm
    )
    return encoded_jwt


def verify_token(token: str) -> dict:
    """
    验证 JWT Token
    
    Args:
        token: JWT Token 字符串
    
    Returns:
        解码后的 payload，如果无效则返回包含 error 的字典
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm]
        )
        return payload
    except JWTError:
        return {"error": "Invalid token"}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_async_db)
) -> User:
    """
    获取当前登录用户（依赖注入 - 异步版本，支持组织上下文）
    
    Args:
        credentials: HTTP Bearer Token
        db: 异步数据库会话
    
    Returns:
        当前用户对象（已加载组织和角色信息）
    
    Raises:
        HTTPException: 如果认证失败
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token = credentials.credentials
    
    # 验证 Token
    payload = verify_token(token)
    if "error" in payload:
        raise credentials_exception
    
    # 获取用户 ID
    user_id: int = payload.get("id")
    if user_id is None:
        raise credentials_exception
    
    # 从数据库获取用户（异步查询）
    user = await AsyncDB.get_by_id(db, User, user_id)
    
    if user is None:
        raise credentials_exception
    
    return user


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    db: AsyncSession = Depends(get_async_db)
) -> Optional[User]:
    """获取当前用户，未登录时返回 None 而非抛异常。"""
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


async def get_user_role_codes(db: AsyncSession, user: User) -> set[str]:
    """获取用户当前生效的角色代码，兼容 User.role 和 RBAC 角色表。"""
    from app.mappers.permission_mapper import AsyncPermissionMapper

    role_codes: set[str] = set()
    user_roles = await AsyncPermissionMapper.get_user_roles(db, user.id)
    for user_role in user_roles:
        if user_role.role and user_role.role.code:
            role_codes.add(user_role.role.code)

    fallback_role = (getattr(user, "role", None) or "").strip()
    if fallback_role:
        role_codes.add(fallback_role)
        if fallback_role == "admin":
            role_codes.add("system_admin")
        elif fallback_role == "teacher":
            role_codes.add("teacher")
        elif fallback_role == "student":
            role_codes.add("student")
        elif fallback_role == "school_admin":
            role_codes.add("admin")

    return role_codes


async def is_system_admin(db: AsyncSession, user: User) -> bool:
    """系统管理员拥有全局配置和权限模型的最高管理权。"""
    role_codes = await get_user_role_codes(db, user)
    return "system_admin" in role_codes or "admin" in role_codes


async def is_school_admin(db: AsyncSession, user: User) -> bool:
    """兼容旧代码，admin 视为学校管理员。"""
    return await is_system_admin(db, user)


async def require_system_admin(db: AsyncSession, user: User) -> None:
    """要求系统管理员权限。"""
    if not await is_system_admin(db, user):
        raise ForbiddenError("需要系统管理员权限")


async def require_any_permission(
    db: AsyncSession,
    user: User,
    permission_codes: Iterable[str],
    organization_id: Optional[int] = None,
    allow_system_admin: bool = True,
) -> None:
    """要求用户至少拥有一个给定权限代码。"""
    if allow_system_admin and await is_system_admin(db, user):
        return

    for permission_code in permission_codes:
        has_permission = await AsyncPermissionService.check_permission(
            db,
            user.id,
            permission_code,
            organization_id,
        )
        if has_permission:
            return

    raise ForbiddenError(f"权限不足，需要以下权限之一: {', '.join(permission_codes)}")


async def get_current_user_with_context(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_async_db)
) -> dict:
    """
    获取当前登录用户及其上下文（组织、角色、权限）
    
    Args:
        credentials: HTTP Bearer Token
        db: 异步数据库会话
    
    Returns:
        包含用户、组织、角色、权限的字典
    
    Raises:
        HTTPException: 如果认证失败
    """
    user = await get_current_user(credentials, db)
    
    # 获取用户所属组织
    organizations = await AsyncOrganizationMapper.get_user_organizations(db, user.id)
    
    # 获取用户角色
    roles = await AsyncPermissionService.get_user_roles(db, user.id)
    
    # 获取用户权限
    permissions = await AsyncPermissionService.get_user_permissions(db, user.id)
    
    # 获取用户学校
    school = None
    if user.school_id:
        school = await AsyncOrganizationMapper.get_organization_by_id(db, user.school_id)
    
    return {
        "user": user,
        "organizations": [org.to_dict() for org in organizations],
        "roles": roles,
        "permissions": permissions,
        "school": school.to_dict() if school else None
    }


def require_permission(permission_code: str):
    """
    权限装饰器：要求用户具有指定权限
    
    Usage:
        @router.get("/endpoint")
        @require_permission("knowledge:read")
        async def endpoint(current_user: User = Depends(get_current_user), ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 从 kwargs 中获取 db 和 current_user
            db: Optional[AsyncSession] = kwargs.get('db')
            current_user: Optional[User] = kwargs.get('current_user')
            
            if not db or not current_user:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database session or user not found"
                )
            
            # 从 kwargs 中获取 organization_id（如果存在）
            organization_id = kwargs.get('organization_id')
            
            # 检查权限
            has_permission = await AsyncPermissionService.check_permission(
                db, current_user.id, permission_code, organization_id
            )
            
            if not has_permission:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied: {permission_code}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_organization_access(permission_code: str = "organization:read"):
    """
    组织访问权限装饰器：要求用户对指定组织有访问权限
    
    Usage:
        @router.get("/organization/{organization_id}/endpoint")
        @require_organization_access("organization:manage")
        async def endpoint(organization_id: int, ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 从 kwargs 中获取 db、current_user 和 organization_id
            db: Optional[AsyncSession] = kwargs.get('db')
            current_user: Optional[User] = kwargs.get('current_user')
            organization_id: Optional[int] = kwargs.get('organization_id')
            
            if not db or not current_user:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database session or user not found"
                )
            
            if not organization_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Organization ID is required"
                )
            
            # 检查组织访问权限
            has_access = await AsyncPermissionService.check_organization_access(
                db, current_user.id, organization_id, permission_code
            )
            
            if not has_access:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied to organization {organization_id}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator
