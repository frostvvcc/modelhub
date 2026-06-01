"""
模型路由
"""
from fastapi import APIRouter, Depends, status, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database_async import get_async_db
from app.utils.auth import get_current_user, get_optional_current_user
from app.schemas.model import ModelConfigCreate, ModelConfigUpdate
from app.schemas.response import SuccessResponse
from app.models.user import User
from app.services.model_service import AsyncModelService
from app.mappers.model_mapper import AsyncModelMapper
from app.mappers.organization_mapper import AsyncOrganizationMapper
from app.services.simple_permission_service import ADMIN_ROLES, SimplePermissionService, UserRole
from app.utils.logger_config import get_logger
from app.utils.error_handler import ValidationError, NotFoundError, ForbiddenError

logger = get_logger(__name__)
router = APIRouter()


class ShareIdRequest(BaseModel):
    share_id: str


async def _user_org_ids(db: AsyncSession, user: User) -> list[int]:
    org_ids: list[int] = []
    if user.school_id:
        org_ids.append(user.school_id)
    user_orgs = await AsyncOrganizationMapper.get_user_organizations(db, user.id)
    for org in user_orgs:
        if org.id not in org_ids:
            org_ids.append(org.id)
        if org.school_id and org.school_id not in org_ids:
            org_ids.append(org.school_id)
    return org_ids


async def _require_model_config_read(db: AsyncSession, user: User, config_id: int) -> None:
    config = await AsyncModelMapper.get_model_config_by_id(db, config_id)
    if not config:
        raise NotFoundError("模型配置不存在")
    role = await SimplePermissionService.get_user_role(db, user)
    if role in ADMIN_ROLES or config.user_id == user.id:
        return
    # 根据 organization_id 判断
    if config.organization_id:
        org_ids = await _user_org_ids(db, user)
        if config.organization_id in org_ids:
            return
    # 通过教学空间访问
    if await SimplePermissionService._user_has_teaching_space_access(db, user.id, "bot", config_id):
        return
    raise ForbiddenError("无权访问该模型配置")


async def _require_model_config_manage(db: AsyncSession, user: User, config_id: int) -> None:
    config = await AsyncModelMapper.get_model_config_by_id(db, config_id)
    if not config:
        raise NotFoundError("模型配置不存在")
    role = await SimplePermissionService.get_user_role(db, user)
    if role not in ADMIN_ROLES and config.user_id != user.id:
        raise ForbiddenError("无权管理该模型配置")


async def _require_model_config_create(db: AsyncSession, user: User, organization_id: Optional[int]) -> None:
    role = await SimplePermissionService.get_user_role(db, user)
    if role == UserRole.STUDENT:
        if organization_id is not None:
            raise ForbiddenError("学生用户只能创建个人私有模型配置")
    if organization_id and role not in ADMIN_ROLES:
        org_ids = await _user_org_ids(db, user)
        if organization_id not in org_ids:
            raise ForbiddenError("无权在该组织创建模型配置")


@router.get(
    "/modelinfo/getlist",
    response_model=SuccessResponse[list],
    summary="获取模型信息列表"
)
async def get_all_info(db: AsyncSession = Depends(get_async_db)):
    """获取所有模型信息"""
    info_list = await AsyncModelService.get_all_info(db)
    return SuccessResponse(message="获取model_info列表成功", data=info_list)


@router.get(
    "/modelinfo/get/{info_id}",
    response_model=SuccessResponse[dict],
    summary="获取模型信息"
)
async def get_info(info_id: int, db: AsyncSession = Depends(get_async_db)):
    """根据ID获取模型信息"""
    model_info = await AsyncModelService.get_info(db, info_id)
    return SuccessResponse(message="获取model_info成功", data=model_info)


@router.get(
    "/modelconfig/getpublic",
    response_model=SuccessResponse[list],
    summary="获取公共模型配置"
)
async def get_public_config(
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取用户可访问的模型配置"""
    if current_user:
        config_list = await AsyncModelService.get_accessible_configs(db, current_user)
    else:
        config_list = await AsyncModelService.get_public_config(db)
    return SuccessResponse(message="获取公共模型配置成功", data=config_list)


@router.get(
    "/modelconfig/get/{config_id}",
    response_model=SuccessResponse[dict],
    summary="获取模型配置"
)
async def get_config_by_id(
    config_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """根据ID获取模型配置"""
    await _require_model_config_read(db, current_user, config_id)
    config = await AsyncModelService.get_model_config_by_id(db, config_id)
    return SuccessResponse(message="获取模型配置成功", data=config)


@router.get(
    "/modelconfig/getuser",
    response_model=SuccessResponse[list],
    summary="获取用户模型配置"
)
async def get_user_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取当前用户的模型配置"""
    config_list = await AsyncModelService.get_user_config(db, current_user)
    return SuccessResponse(message="获取用户模型配置成功", data=config_list)


@router.get(
    "/modelconfig/getuser/{user_id}",
    response_model=SuccessResponse[list],
    summary="获取指定用户可访问的模型配置"
)
async def get_user_config_by_id(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取指定用户创建且当前用户可访问的模型配置。"""
    configs = await AsyncModelMapper.get_model_config_by_user_id(db, user_id)
    accessible_configs = []
    for config in configs:
        try:
            await _require_model_config_read(db, current_user, config.id)
        except ForbiddenError:
            continue
        accessible_configs.append(await AsyncModelService.get_model_config_by_id(db, config.id))
    return SuccessResponse(message="获取用户模型配置成功", data=accessible_configs)


@router.post(
    "/modelconfig/getshare",
    response_model=SuccessResponse[dict],
    summary="根据分享 ID 获取模型配置"
)
async def get_model_config_by_share_id(
    request: ShareIdRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """根据分享 ID 获取当前用户可访问的模型配置。"""
    config = await AsyncModelMapper.get_model_config_by_share_id(db, request.share_id.strip())
    if not config:
        raise NotFoundError("模型配置不存在")
    await _require_model_config_read(db, current_user, config.id)
    data = await AsyncModelService.get_model_config_by_id(db, config.id)
    return SuccessResponse(message="获取模型配置成功", data=data)


@router.post(
    "/modelconfig/create",
    response_model=SuccessResponse[dict],
    status_code=status.HTTP_201_CREATED,
    summary="创建模型配置"
)
async def create_model_config(
    request: ModelConfigCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """创建新的模型配置"""
    await _require_model_config_create(db, current_user, request.organization_id)
    config = await AsyncModelService.create_model_config(
        db,
        current_user.id,
        request.share_id,
        request.base_model_id,
        request.name,
        request.temperature,
        request.top_p,
        request.prompt,
        prompt_variables=request.prompt_variables,
        knowledge_context_template=request.knowledge_context_template,
        citation_template=request.citation_template,
        refusal_strategy=request.refusal_strategy,
        max_context_chars=request.max_context_chars,
        answer_with_citations=request.answer_with_citations,
        describe=request.describe,
        organization_id=request.organization_id,
    )
    return SuccessResponse(message="创建模型配置成功", data=config)


@router.post(
    "/modelconfig/update",
    response_model=SuccessResponse[dict],
    summary="更新模型配置"
)
async def update_model_config(
    request: ModelConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """更新模型配置"""
    if not request.id:
        raise ValidationError("更新配置id不能为空")
    await _require_model_config_manage(db, current_user, request.id)

    config = await AsyncModelService.update_model_config(
        db,
        model_config_id=request.id,
        share_id=request.share_id,
        base_model_id=request.base_model_id,
        name=request.name,
        temperature=request.temperature,
        top_p=request.top_p,
        prompt=request.prompt,
        prompt_variables=request.prompt_variables,
        knowledge_context_template=request.knowledge_context_template,
        citation_template=request.citation_template,
        refusal_strategy=request.refusal_strategy,
        max_context_chars=request.max_context_chars,
        answer_with_citations=request.answer_with_citations,
        describe=request.describe,
        organization_id=request.organization_id,
    )
    return SuccessResponse(message="模型配置更新成功", data=config)


@router.delete(
    "/modelconfig/delete/{config_id}",
    response_model=SuccessResponse[dict],
    summary="删除模型配置"
)
async def delete_model_config(
    config_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """删除模型配置"""
    await _require_model_config_manage(db, current_user, config_id)
    config = await AsyncModelService.delete_model_config(db, config_id)
    return SuccessResponse(message="模型配置删除成功", data=config)
