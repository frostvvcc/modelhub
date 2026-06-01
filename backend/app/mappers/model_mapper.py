"""
异步模型 Mapper
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.model_config import ModelConfig
from app.models.model_info import ModelInfo
from app.utils.async_db import AsyncDB
from app.mappers.user_mapper import AsyncUserMapper
import logging

logger = logging.getLogger(__name__)


class AsyncModelMapper:
    """异步模型数据访问层"""
    
    @staticmethod
    async def get_model_info_by_id(session: AsyncSession, model_info_id: int) -> Optional[ModelInfo]:
        """根据 ID 获取模型信息（包含供应商信息）"""
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select
        
        stmt = select(ModelInfo).options(selectinload(ModelInfo.provider)).where(ModelInfo.id == model_info_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_all_model_info(session: AsyncSession) -> list[ModelInfo]:
        """获取所有模型信息"""
        return await AsyncDB.get_all(session, ModelInfo)
    
    @staticmethod
    async def get_model_config_by_id(session: AsyncSession, model_config_id: int) -> Optional[ModelConfig]:
        """根据 ID 获取模型配置"""
        # 验证 ID 是否有效
        if not model_config_id or model_config_id <= 0:
            return None
        config = await AsyncDB.get_by_id(session, ModelConfig, model_config_id)
        return config

    @staticmethod
    async def get_model_config_by_share_id(session: AsyncSession, share_id: str) -> Optional[ModelConfig]:
        """根据分享 ID 获取模型配置。"""
        if not share_id:
            return None
        stmt = select(ModelConfig).where(ModelConfig.share_id == share_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_model_config_by_user_id(
        session: AsyncSession,
        user_id: int,
        school_id: Optional[int] = None,
        organization_id: Optional[int] = None
    ) -> list[ModelConfig]:
        """根据用户 ID 获取模型配置列表（基于 organization_id 过滤）"""
        from sqlalchemy import select, or_

        conditions = [ModelConfig.user_id == user_id]

        org_ids = set()
        if organization_id:
            org_ids.add(organization_id)
        if school_id:
            org_ids.add(school_id)

        if org_ids:
            conditions.append(ModelConfig.organization_id.in_(org_ids))

        stmt = select(ModelConfig).where(or_(*conditions)).order_by(ModelConfig.id)
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_all_public_model_config(
        session: AsyncSession,
        school_id: Optional[int] = None,
        organization_id: Optional[int] = None
    ) -> list[ModelConfig]:
        """获取公开的模型配置（organization_id 不为空的）"""
        from sqlalchemy import select, or_

        org_ids = set()
        if organization_id:
            org_ids.add(organization_id)
        if school_id:
            org_ids.add(school_id)

        if org_ids:
            stmt = select(ModelConfig).where(
                ModelConfig.organization_id.in_(org_ids)
            ).order_by(ModelConfig.id)
        else:
            stmt = select(ModelConfig).where(
                ModelConfig.organization_id.isnot(None)
            ).order_by(ModelConfig.id)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    
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
        **kwargs,
    ) -> ModelConfig:
        """创建模型配置"""
        try:
            user = await AsyncUserMapper.get_user_by_id(session, user_id)
            if not user:
                raise ValueError("user not exist")

            base_model = await AsyncModelMapper.get_model_info_by_id(session, base_model_id)
            if not base_model:
                raise ValueError("base_model not exist")

            model_config = ModelConfig(
                user_id=user_id,
                share_id=share_id,
                base_model_id=base_model_id,
                name=name,
                temperature=temperature,
                top_p=top_p,
                prompt=prompt,
                prompt_variables=prompt_variables,
                knowledge_context_template=knowledge_context_template,
                citation_template=citation_template,
                refusal_strategy=refusal_strategy,
                max_context_chars=max_context_chars,
                answer_with_citations=answer_with_citations,
                describe=describe,
                organization_id=organization_id,
            )

            model_config = await AsyncDB.create(session, model_config)
            await AsyncDB.commit(session)
            return model_config
        except ValueError as ve:
            await AsyncDB.rollback(session)
            raise ve
        except Exception as e:
            await AsyncDB.rollback(session)
            raise Exception(f"模型配置创建失败: {str(e)}")
    
    @staticmethod
    async def update_model_config_by_id(
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
        **kwargs,
    ) -> ModelConfig:
        """更新模型配置"""
        try:
            model_config = await AsyncModelMapper.get_model_config_by_id(session, model_config_id)
            if not model_config:
                raise ValueError("model config not exist")

            if share_id is not None:
                model_config.share_id = share_id
            if base_model_id is not None:
                model_config.base_model_id = base_model_id
            if name is not None:
                model_config.name = name
            if temperature is not None:
                model_config.temperature = temperature
            if top_p is not None:
                model_config.top_p = top_p
            if prompt is not None:
                model_config.prompt = prompt
            if prompt_variables is not None:
                model_config.prompt_variables = prompt_variables
            if knowledge_context_template is not None:
                model_config.knowledge_context_template = knowledge_context_template
            if citation_template is not None:
                model_config.citation_template = citation_template
            if refusal_strategy is not None:
                model_config.refusal_strategy = refusal_strategy
            if max_context_chars is not None:
                model_config.max_context_chars = max_context_chars
            if answer_with_citations is not None:
                model_config.answer_with_citations = answer_with_citations
            if describe is not None:
                model_config.describe = describe
            if organization_id is not None:
                model_config.organization_id = organization_id

            model_config = await AsyncDB.update(session, model_config)
            await AsyncDB.commit(session)
            return model_config
        except Exception as e:
            await AsyncDB.rollback(session)
            raise Exception(f"更新模型配置失败: {str(e)}")
    
    @staticmethod
    async def delete_model_config_by_id(session: AsyncSession, config_id: int) -> ModelConfig:
        """删除模型配置"""
        try:
            model_config = await AsyncModelMapper.get_model_config_by_id(session, config_id)
            if not model_config:
                raise ValueError("model config not exist")
            
            await AsyncDB.delete(session, model_config)
            await AsyncDB.commit(session)
            return model_config
        except ValueError as ve:
            await AsyncDB.rollback(session)
            raise ve
        except Exception as e:
            await AsyncDB.rollback(session)
            raise Exception(f"模型配置删除失败: {str(e)}")
    
