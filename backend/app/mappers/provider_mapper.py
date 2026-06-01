"""
供应商配置 Mapper
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from typing import List, Optional
from app.models.provider_config import ProviderConfig
from app.utils.async_db import AsyncDB
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


class AsyncProviderMapper:
    """异步供应商配置数据访问层"""
    
    @staticmethod
    async def get_provider_by_id(session: AsyncSession, provider_id: int) -> Optional[ProviderConfig]:
        """根据 ID 获取供应商配置"""
        return await AsyncDB.get_by_id(session, ProviderConfig, provider_id)
    
    @staticmethod
    async def get_provider_by_code(session: AsyncSession, code: str) -> Optional[ProviderConfig]:
        """根据代码获取供应商配置"""
        return await AsyncDB.get_by_field(session, ProviderConfig, "code", code)
    
    @staticmethod
    async def get_all_providers(
        session: AsyncSession,
        is_active: Optional[bool] = None,
        provider_type: Optional[str] = None
    ) -> List[ProviderConfig]:
        """获取所有供应商配置"""
        stmt = select(ProviderConfig)
        
        conditions = []
        if is_active is not None:
            conditions.append(ProviderConfig.is_active == is_active)
        if provider_type:
            conditions.append(ProviderConfig.provider_type == provider_type)
        
        if conditions:
            stmt = stmt.where(and_(*conditions))
        
        stmt = stmt.order_by(ProviderConfig.priority.desc(), ProviderConfig.id)
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_default_provider(
        session: AsyncSession,
        provider_type: Optional[str] = None
    ) -> Optional[ProviderConfig]:
        """获取默认供应商配置"""
        stmt = select(ProviderConfig).where(ProviderConfig.is_default == True)
        
        if provider_type:
            stmt = stmt.where(ProviderConfig.provider_type == provider_type)
        
        stmt = stmt.order_by(ProviderConfig.priority.desc())
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create_provider(
        session: AsyncSession,
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
        supported_model_types: Optional[str] = None
    ) -> ProviderConfig:
        """创建供应商配置"""
        # 检查代码是否已存在
        existing = await AsyncProviderMapper.get_provider_by_code(session, code)
        if existing:
            raise ValueError(f"Provider code '{code}' already exists")
        
        # 如果设置为默认，取消其他默认设置
        if is_default:
            await AsyncProviderMapper._unset_default_providers(session, provider_type)
        
        provider = ProviderConfig(
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
        
        provider = await AsyncDB.create(session, provider)
        await AsyncDB.commit(session)
        return provider
    
    @staticmethod
    async def _unset_default_providers(session: AsyncSession, provider_type: Optional[str] = None):
        """取消其他默认供应商设置"""
        stmt = select(ProviderConfig).where(ProviderConfig.is_default == True)
        if provider_type:
            stmt = stmt.where(ProviderConfig.provider_type == provider_type)
        
        result = await session.execute(stmt)
        providers = result.scalars().all()
        for provider in providers:
            provider.is_default = False
        await session.flush()
    
    @staticmethod
    async def update_provider(
        session: AsyncSession,
        provider_id: int,
        **kwargs
    ) -> Optional[ProviderConfig]:
        """更新供应商配置"""
        provider = await AsyncProviderMapper.get_provider_by_id(session, provider_id)
        if not provider:
            return None
        
        # 如果设置为默认，取消其他默认设置
        if kwargs.get('is_default') is True:
            await AsyncProviderMapper._unset_default_providers(session, provider.provider_type)
        
        for key, value in kwargs.items():
            if hasattr(provider, key) and value is not None:
                setattr(provider, key, value)
        
        await AsyncDB.update(session, provider)
        await AsyncDB.commit(session)
        return provider
    
    @staticmethod
    async def delete_provider(session: AsyncSession, provider_id: int) -> bool:
        """删除供应商配置"""
        provider = await AsyncProviderMapper.get_provider_by_id(session, provider_id)
        if not provider:
            return False
        
        # 检查是否有模型使用此供应商
        from app.models.model_info import ModelInfo
        stmt = select(ModelInfo).where(ModelInfo.provider_id == provider_id)
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            raise ValueError("Cannot delete provider: models are using it")
        
        await AsyncDB.delete(session, provider)
        await AsyncDB.commit(session)
        return True

