"""
供应商配置路由
"""
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from app.database_async import get_async_db
from app.utils.auth import get_current_user, get_optional_current_user, require_any_permission, require_system_admin
from app.schemas.response import SuccessResponse
from app.models.user import User
from app.services.provider_service import AsyncProviderService
from app.utils.logger_config import get_logger
from app.utils.error_handler import ValidationError

logger = get_logger(__name__)
router = APIRouter()


@router.get(
    "/providers",
    response_model=SuccessResponse[List[dict]],
    summary="获取所有供应商配置"
)
async def get_all_providers(
    is_active: Optional[bool] = Query(None, description="是否启用"),
    provider_type: Optional[str] = Query(None, description="供应商类型"),
    include_sensitive: bool = Query(False, description="是否包含敏感信息"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取所有供应商配置，敏感信息需要管理员权限"""
    if include_sensitive:
        if not current_user:
            raise ValidationError("查看敏感信息需要登录")
        await require_system_admin(db, current_user)
    result = await AsyncProviderService.get_all_providers(
        db, is_active=is_active, provider_type=provider_type, include_sensitive=include_sensitive
    )
    return SuccessResponse(message="查询成功", data=result)


@router.get(
    "/provider/{provider_id}",
    response_model=SuccessResponse[dict],
    summary="获取供应商配置详情"
)
async def get_provider(
    provider_id: int,
    include_sensitive: bool = Query(False, description="是否包含敏感信息"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取供应商配置详情"""
    if include_sensitive:
        await require_system_admin(db, current_user)
    else:
        await require_any_permission(
            db,
            current_user,
            ["config:read", "config:write", "config:manage"],
        )
    result = await AsyncProviderService.get_provider(
        db, provider_id, include_sensitive=include_sensitive
    )
    return SuccessResponse(message="查询成功", data=result)


@router.get(
    "/provider/code/{code}",
    response_model=SuccessResponse[dict],
    summary="根据代码获取供应商配置"
)
async def get_provider_by_code(
    code: str,
    include_sensitive: bool = Query(False, description="是否包含敏感信息"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """根据代码获取供应商配置"""
    if include_sensitive:
        await require_system_admin(db, current_user)
    else:
        await require_any_permission(
            db,
            current_user,
            ["config:read", "config:write", "config:manage"],
        )
    result = await AsyncProviderService.get_provider_by_code(
        db, code, include_sensitive=include_sensitive
    )
    return SuccessResponse(message="查询成功", data=result)


@router.get(
    "/provider/default",
    response_model=SuccessResponse[dict],
    summary="获取默认供应商配置"
)
async def get_default_provider(
    provider_type: Optional[str] = Query(None, description="供应商类型"),
    include_sensitive: bool = Query(False, description="是否包含敏感信息"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取默认供应商配置"""
    if include_sensitive:
        await require_system_admin(db, current_user)
    else:
        await require_any_permission(
            db,
            current_user,
            ["config:read", "config:write", "config:manage"],
        )
    result = await AsyncProviderService.get_default_provider(
        db, provider_type=provider_type, include_sensitive=include_sensitive
    )
    if not result:
        return SuccessResponse(message="未找到默认供应商配置", data=None)
    return SuccessResponse(message="查询成功", data=result)


@router.post(
    "/provider",
    response_model=SuccessResponse[dict],
    status_code=status.HTTP_201_CREATED,
    summary="创建供应商配置"
)
async def create_provider(
    name: str,
    code: str,
    provider_type: str,
    base_url: str,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    config_json: Optional[str] = None,
    description: Optional[str] = None,
    is_active: bool = True,
    is_default: bool = False,
    priority: int = 0,
    rate_limit: Optional[int] = None,
    max_tokens: Optional[int] = None,
    supported_model_types: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """创建供应商配置"""
    await require_system_admin(db, current_user)
    if not name or not code or not provider_type or not base_url:
        raise ValidationError("供应商名称、代码、类型和基础 URL 不能为空")
    
    result = await AsyncProviderService.create_provider(
        db,
        name=name,
        code=code,
        provider_type=provider_type,
        base_url=base_url,
        api_key=api_key,
        api_secret=api_secret,
        config_json=config_json,
        description=description,
        is_active=is_active,
        is_default=is_default,
        priority=priority,
        rate_limit=rate_limit,
        max_tokens=max_tokens,
        supported_model_types=supported_model_types
    )
    return SuccessResponse(message="创建成功", data=result)


@router.put(
    "/provider/{provider_id}",
    response_model=SuccessResponse[dict],
    summary="更新供应商配置"
)
async def update_provider(
    provider_id: int,
    name: Optional[str] = None,
    code: Optional[str] = None,
    provider_type: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    config_json: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
    is_default: Optional[bool] = None,
    priority: Optional[int] = None,
    rate_limit: Optional[int] = None,
    max_tokens: Optional[int] = None,
    supported_model_types: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """更新供应商配置"""
    await require_system_admin(db, current_user)
    kwargs = {}
    if name is not None:
        kwargs['name'] = name
    if code is not None:
        kwargs['code'] = code
    if provider_type is not None:
        kwargs['provider_type'] = provider_type
    if base_url is not None:
        kwargs['base_url'] = base_url
    if api_key is not None:
        kwargs['api_key'] = api_key
    if api_secret is not None:
        kwargs['api_secret'] = api_secret
    if config_json is not None:
        kwargs['config_json'] = config_json
    if description is not None:
        kwargs['description'] = description
    if is_active is not None:
        kwargs['is_active'] = is_active
    if is_default is not None:
        kwargs['is_default'] = is_default
    if priority is not None:
        kwargs['priority'] = priority
    if rate_limit is not None:
        kwargs['rate_limit'] = rate_limit
    if max_tokens is not None:
        kwargs['max_tokens'] = max_tokens
    if supported_model_types is not None:
        kwargs['supported_model_types'] = supported_model_types
    
    result = await AsyncProviderService.update_provider(db, provider_id, **kwargs)
    return SuccessResponse(message="更新成功", data=result)


@router.delete(
    "/provider/{provider_id}",
    response_model=SuccessResponse[dict],
    summary="删除供应商配置"
)
async def delete_provider(
    provider_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """删除供应商配置"""
    await require_system_admin(db, current_user)
    result = await AsyncProviderService.delete_provider(db, provider_id)
    return SuccessResponse(message="删除成功", data={"deleted": result})
