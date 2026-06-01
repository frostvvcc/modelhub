"""
异步模型 Service
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.mappers.model_mapper import AsyncModelMapper
from app.mappers.user_mapper import AsyncUserMapper
from app.utils.logger_config import get_logger
from app.utils.error_handler import NotFoundError, InternalServerError

logger = get_logger(__name__)


class AsyncModelService:
    """异步模型服务类"""
    
    @staticmethod
    async def get_all_info(session: AsyncSession) -> list:
        """
        获取所有模型信息
        
        Raises:
            InternalServerError: 获取失败
        """
        logger.debug("获取所有模型信息")
        try:
            info_list = await AsyncModelMapper.get_all_model_info(session)
            logger.debug(f"成功获取模型信息列表: 共 {len(info_list)} 个")
            return [{
                "id": info.id,
                "model_name": info.model_name,
                "describe": info.describe,
                "type": info.type
            } for info in info_list]
        except Exception as e:
            logger.error(f"获取模型信息列表失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"获取info列表失败: {str(e)}")
    
    @staticmethod
    async def get_info(session: AsyncSession, info_id: int) -> dict:
        """
        根据ID获取模型信息
        
        Raises:
            NotFoundError: 模型信息不存在
            InternalServerError: 获取失败
        """
        logger.debug(f"获取模型信息: info_id={info_id}")
        try:
            model_info = await AsyncModelMapper.get_model_info_by_id(session, info_id)
            if not model_info:
                logger.warning(f"获取模型信息失败: 不存在 - info_id={info_id}")
                raise NotFoundError("模型信息不存在")
            
            logger.debug(f"成功获取模型信息: info_id={info_id}")
            return {
                "id": model_info.id,
                "model_name": model_info.model_name,
                "describe": model_info.describe,
                "type": model_info.type
            }
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"获取模型信息失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"获取info失败: {str(e)}")
    
    @staticmethod
    async def get_public_config(
        session: AsyncSession,
        school_id: Optional[int] = None,
        organization_id: Optional[int] = None
    ) -> list:
        """
        获取所有公开模型配置（根据组织架构过滤）
        
        Raises:
            InternalServerError: 获取失败
        """
        logger.debug(f"获取所有公开模型配置: school_id={school_id}, organization_id={organization_id}")
        try:
            config_list = await AsyncModelMapper.get_all_public_model_config(
                session, school_id=school_id, organization_id=organization_id
            )

            # 批量预加载用户和模型信息，避免 N+1 查询
            user_ids = list({c.user_id for c in config_list if c.user_id})
            model_ids = list({c.base_model_id for c in config_list if c.base_model_id})

            users_map = {}
            for uid in user_ids:
                u = await AsyncUserMapper.get_user_by_id(session, uid)
                if u:
                    users_map[uid] = u

            models_map = {}
            for mid in model_ids:
                m = await AsyncModelMapper.get_model_info_by_id(session, mid)
                if m:
                    models_map[mid] = m

            model_config_list = []
            for config in config_list:
                user = users_map.get(config.user_id)
                base_model = models_map.get(config.base_model_id)

                provider_name = None
                provider_code = None
                if base_model and base_model.provider:
                    provider_name = base_model.provider.name
                    provider_code = base_model.provider.code

                model_config_list.append({
                    "id": config.id,
                    "name": config.name,
                    "author": user.name if user else "未知",
                    "base_model_name": base_model.model_name if base_model else "未知",
                    "provider_name": provider_name,
                    "provider_code": provider_code,
                    "describe": config.describe,
                    "organization_id": config.organization_id,
                    "update_at": config.update_at.isoformat() if config.update_at else None
                })
            logger.debug(f"成功获取公开模型配置: 共 {len(model_config_list)} 个")
            return model_config_list
        except Exception as e:
            logger.error(f"获取公共配置失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"获取公共配置失败: {str(e)}")
    
    @staticmethod
    async def get_model_config_by_id(session: AsyncSession, config_id: int) -> dict:
        """
        根据ID获取模型配置
        
        Raises:
            NotFoundError: 模型配置不存在
            InternalServerError: 获取失败
        """
        logger.debug(f"获取模型配置: config_id={config_id}")
        
        # 验证 config_id 是否有效
        if not config_id or config_id <= 0:
            logger.warning(f"获取模型配置失败: 无效的配置ID - config_id={config_id}")
            raise NotFoundError("模型配置不存在")
        
        try:
            config = await AsyncModelMapper.get_model_config_by_id(session, config_id)
            if not config:
                logger.warning(f"获取模型配置失败: 不存在 - config_id={config_id}")
                raise NotFoundError("模型配置不存在")
            
            user_id = config.user_id
            user = await AsyncUserMapper.get_user_by_id(session, user_id)
            
            base_model_id = config.base_model_id
            base_model = await AsyncModelMapper.get_model_info_by_id(session, base_model_id)
            
            logger.debug(f"成功获取模型配置: config_id={config_id}")
            return {
                "id": config.id,
                "share_id": config.share_id,
                "name": config.name,
                "user_id": config.user_id,
                "author": user.name if user else "未知",
                "base_model_id": config.base_model_id,
                "base_model_name": base_model.model_name if base_model else "未知",
                "describe": config.describe,
                "prompt": config.prompt,
                "prompt_variables": config.prompt_variables,
                "knowledge_context_template": config.knowledge_context_template,
                "citation_template": config.citation_template,
                "refusal_strategy": config.refusal_strategy,
                "max_context_chars": config.max_context_chars,
                "answer_with_citations": config.answer_with_citations,

                "organization_id": config.organization_id,
                "created_at": config.create_at.isoformat() if config.create_at else None,
                "update_at": config.update_at.isoformat() if config.update_at else None
            }
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"获取模型配置失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"获取模型配置失败: {str(e)}")

    @staticmethod
    async def get_model_config_by_share_id(session: AsyncSession, share_id: str) -> dict:
        """根据分享 ID 获取模型配置。"""
        logger.debug(f"根据分享ID获取模型配置: share_id={share_id}")
        try:
            config = await AsyncModelMapper.get_model_config_by_share_id(session, share_id)
            if not config:
                raise NotFoundError("模型配置不存在")
            return await AsyncModelService.get_model_config_by_id(session, config.id)
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"根据分享ID获取模型配置失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"根据分享ID获取模型配置失败: {str(e)}")
    
    @staticmethod
    async def get_user_config(session: AsyncSession, user) -> list:
        """
        获取用户模型配置（根据组织架构过滤）
        
        Raises:
            InternalServerError: 获取失败
        """
        user_id = user.id
        logger.debug(f"获取用户模型配置: user_id={user_id}")
        try:
            # 获取用户的组织和学校信息
            from app.mappers.organization_mapper import AsyncOrganizationMapper
            user_orgs = await AsyncOrganizationMapper.get_user_organizations(session, user_id)
            
            # 确定用户的组织上下文
            organization_id = user_orgs[0].id if user_orgs else None
            school_id = user.school_id or (user_orgs[0].school_id if user_orgs else None)
            
            config_list = await AsyncModelMapper.get_model_config_by_user_id(
                session, user_id, school_id=school_id, organization_id=organization_id
            )

            owner_ids = list({c.user_id for c in config_list if c.user_id})
            users_map = {}
            for uid in owner_ids:
                u = await AsyncUserMapper.get_user_by_id(session, uid)
                if u:
                    users_map[uid] = u

            model_config_list = []
            for config in config_list:
                owner = users_map.get(config.user_id)
                model_config_list.append({
                    "id": config.id,
                    "user_id": config.user_id,
                    "author_name": owner.name if owner else "未知",
                    "name": config.name,
                    "describe": config.describe,
                    "share_id": config.share_id,
                    "base_model_id": config.base_model_id,
                    "temperature": float(config.temperature),
                    "top_p": float(config.top_p),
                    "prompt": config.prompt,
                    "prompt_variables": config.prompt_variables,
                    "knowledge_context_template": config.knowledge_context_template,
                    "citation_template": config.citation_template,
                    "refusal_strategy": config.refusal_strategy,
                    "max_context_chars": config.max_context_chars,
                    "answer_with_citations": config.answer_with_citations,
    
    
                    "organization_id": config.organization_id,
                    "created_at": config.create_at.isoformat() if config.create_at else None,
                    "updated_at": config.update_at.isoformat() if config.update_at else None,
                })
            logger.debug(f"成功获取用户模型配置: user_id={user_id}, 共 {len(model_config_list)} 个")
            return model_config_list
        except Exception as e:
            logger.error(f"获取用户配置失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"获取用户配置失败: {str(e)}")
    
    @staticmethod
    async def create_model_config(
        session: AsyncSession,
        user_id: int,
        share_id: str,
        base_model_id: int,
        name: str,
        temperature: float,
        top_p: float,
        prompt: Optional[str],
        prompt_variables: Optional[str] = None,
        knowledge_context_template: Optional[str] = None,
        citation_template: Optional[str] = None,
        refusal_strategy: Optional[str] = None,
        max_context_chars: int = 6000,
        answer_with_citations: bool = True,
        describe: Optional[str] = None,
        organization_id: Optional[int] = None,
        **kwargs
    ) -> dict:
        """
        创建模型配置

        Raises:
            InternalServerError: 创建失败
        """
        logger.info(f"创建模型配置: user_id={user_id}, name={name}, organization_id={organization_id}")
        try:
            config = await AsyncModelMapper.create_model_config(
                session,
                user_id,
                share_id,
                base_model_id,
                name,
                temperature,
                top_p,
                prompt,
                prompt_variables,
                knowledge_context_template,
                citation_template,
                refusal_strategy,
                max_context_chars,
                answer_with_citations,
                describe,
                organization_id=organization_id,
            )
            logger.info(f"成功创建模型配置: config_id={config.id}")
            return {
                "id": config.id,
                "name": config.name,
                "describe": config.describe,
                "base_model_id": config.base_model_id,
                "temperature": float(config.temperature),
                "top_p": float(config.top_p),
                "prompt": config.prompt,
                "prompt_variables": config.prompt_variables,
                "knowledge_context_template": config.knowledge_context_template,
                "citation_template": config.citation_template,
                "refusal_strategy": config.refusal_strategy,
                "max_context_chars": config.max_context_chars,
                "answer_with_citations": config.answer_with_citations,

                "organization_id": config.organization_id,
                "created_at": config.create_at.isoformat() if config.create_at else None,
                "updated_at": config.update_at.isoformat() if config.update_at else None,
            }
        except Exception as e:
            logger.error(f"创建模型配置失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"创建模型配置失败: {str(e)}")
    
    @staticmethod
    async def update_model_config(
        session: AsyncSession,
        model_config_id: int,
        share_id: Optional[str] = None,
        base_model_id: Optional[int] = None,
        name: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        prompt: Optional[str] = None,
        prompt_variables: Optional[str] = None,
        knowledge_context_template: Optional[str] = None,
        citation_template: Optional[str] = None,
        refusal_strategy: Optional[str] = None,
        max_context_chars: Optional[int] = None,
        answer_with_citations: Optional[bool] = None,
        describe: Optional[str] = None,
        organization_id: Optional[int] = None,
        **kwargs
    ) -> dict:
        """
        更新模型配置

        Raises:
            NotFoundError: 模型配置不存在
            InternalServerError: 更新失败
        """
        logger.info(f"更新模型配置: config_id={model_config_id}")
        try:
            config = await AsyncModelMapper.update_model_config_by_id(
                session,
                model_config_id,
                share_id,
                base_model_id,
                name,
                temperature,
                top_p,
                prompt,
                prompt_variables,
                knowledge_context_template,
                citation_template,
                refusal_strategy,
                max_context_chars,
                answer_with_citations,
                describe,
                organization_id,
            )
            if not config:
                logger.warning(f"更新模型配置失败: 不存在 - config_id={model_config_id}")
                raise NotFoundError("模型配置不存在")

            try:
                from app.utils.async_llm_pool import AsyncLLMPool
                await AsyncLLMPool.clear_cache(model_config_id)
            except Exception as cache_exc:
                logger.warning(f"清除模型客户端缓存失败: config_id={model_config_id}, error={cache_exc}")
            
            logger.info(f"成功更新模型配置: config_id={model_config_id}")
            return {
                "id": config.id,
                "name": config.name,
                "describe": config.describe,
                "base_model_id": config.base_model_id,
                "temperature": float(config.temperature),
                "top_p": float(config.top_p),
                "prompt": config.prompt,
                "prompt_variables": config.prompt_variables,
                "knowledge_context_template": config.knowledge_context_template,
                "citation_template": config.citation_template,
                "refusal_strategy": config.refusal_strategy,
                "max_context_chars": config.max_context_chars,
                "answer_with_citations": config.answer_with_citations,

                "organization_id": config.organization_id,
                "created_at": config.create_at.isoformat() if config.create_at else None,
                "updated_at": config.update_at.isoformat() if config.update_at else None,
            }
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"更新模型配置失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"更新模型配置失败: {str(e)}")
    
    @staticmethod
    async def delete_model_config(session: AsyncSession, config_id: int) -> dict:
        """
        删除模型配置
        
        Raises:
            NotFoundError: 模型配置不存在
            InternalServerError: 删除失败
        """
        logger.info(f"删除模型配置: config_id={config_id}")
        try:
            config = await AsyncModelMapper.delete_model_config_by_id(session, config_id)
            if not config:
                logger.warning(f"删除模型配置失败: 不存在 - config_id={config_id}")
                raise NotFoundError("模型配置不存在")
            
            logger.info(f"成功删除模型配置: config_id={config_id}")
            return {
                "id": config.id,
                "name": config.name
            }
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"删除模型配置失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"删除模型配置失败: {str(e)}")

    @staticmethod
    async def get_accessible_configs(session: AsyncSession, user) -> list:
        """获取用户可访问的所有模型配置（自己的 + 组织归属的 + 教学空间的）"""
        from app.mappers.organization_mapper import AsyncOrganizationMapper
        from app.models.organization import OrganizationMember, Organization
        from app.models.model_config import ModelConfig
        from app.models.teaching_space import TeachingSpaceMajor, TeachingSpaceResource
        from sqlalchemy import select, or_
        from sqlalchemy.orm import selectinload

        user_id = user.id
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

        conditions = [ModelConfig.user_id == user_id]
        if user_org_ids:
            conditions.append(ModelConfig.organization_id.in_(user_org_ids))

        stmt = select(ModelConfig).where(or_(*conditions))
        result = await session.execute(stmt)
        configs = list(result.scalars().all())

        return [
            {
                "id": c.id,
                "name": c.name,
                "user_id": c.user_id,
                "describe": c.describe,
                "organization_id": c.organization_id,
                "update_at": c.update_at.isoformat() if c.update_at else None,
            }
            for c in configs
        ]
