"""
供应商配置服务
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.mappers.provider_mapper import AsyncProviderMapper
from app.utils.logger_config import get_logger
from app.utils.error_handler import NotFoundError, ValidationError, InternalServerError

logger = get_logger(__name__)


class AsyncProviderService:
    """异步供应商配置服务类"""
    
    @staticmethod
    async def get_provider(
        session: AsyncSession,
        provider_id: int,
        include_sensitive: bool = False
    ) -> Dict[str, Any]:
        """获取供应商配置"""
        logger.debug(f"获取供应商配置: provider_id={provider_id}")
        
        provider = await AsyncProviderMapper.get_provider_by_id(session, provider_id)
        if not provider:
            raise NotFoundError("供应商配置不存在")
        
        return provider.to_dict(include_sensitive=include_sensitive)
    
    @staticmethod
    async def get_provider_by_code(
        session: AsyncSession,
        code: str,
        include_sensitive: bool = False
    ) -> Dict[str, Any]:
        """根据代码获取供应商配置"""
        logger.debug(f"获取供应商配置: code={code}")
        
        provider = await AsyncProviderMapper.get_provider_by_code(session, code)
        if not provider:
            raise NotFoundError("供应商配置不存在")
        
        return provider.to_dict(include_sensitive=include_sensitive)
    
    @staticmethod
    async def get_all_providers(
        session: AsyncSession,
        is_active: Optional[bool] = None,
        provider_type: Optional[str] = None,
        include_sensitive: bool = False
    ) -> List[Dict[str, Any]]:
        """获取所有供应商配置"""
        logger.debug(f"获取所有供应商配置: is_active={is_active}, provider_type={provider_type}")
        
        providers = await AsyncProviderMapper.get_all_providers(
            session, is_active=is_active, provider_type=provider_type
        )
        
        return [p.to_dict(include_sensitive=include_sensitive) for p in providers]
    
    @staticmethod
    async def get_default_provider(
        session: AsyncSession,
        provider_type: Optional[str] = None,
        include_sensitive: bool = False
    ) -> Optional[Dict[str, Any]]:
        """获取默认供应商配置"""
        logger.debug(f"获取默认供应商配置: provider_type={provider_type}")
        
        provider = await AsyncProviderMapper.get_default_provider(session, provider_type)
        if not provider:
            return None
        
        return provider.to_dict(include_sensitive=include_sensitive)
    
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
    ) -> Dict[str, Any]:
        """创建供应商配置"""
        logger.info(f"创建供应商配置: name={name}, code={code}, type={provider_type}")
        
        try:
            # 验证供应商类型
            valid_types = ['openai', 'aliyun', 'anthropic', 'local', 'custom']
            if provider_type not in valid_types:
                raise ValidationError(f"无效的供应商类型: {provider_type}")
            
            provider = await AsyncProviderMapper.create_provider(
                session=session,
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
            
            logger.info(f"成功创建供应商配置: id={provider.id}")
            return provider.to_dict(include_sensitive=True)
            
        except ValidationError:
            raise
        except ValueError as e:
            logger.warning(f"创建供应商配置失败: {str(e)}")
            raise ValidationError(str(e))
        except Exception as e:
            logger.error(f"创建供应商配置失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"创建供应商配置失败: {str(e)}")
    
    @staticmethod
    async def update_provider(
        session: AsyncSession,
        provider_id: int,
        **kwargs
    ) -> Dict[str, Any]:
        """更新供应商配置"""
        logger.info(f"更新供应商配置: provider_id={provider_id}")
        
        try:
            provider = await AsyncProviderMapper.update_provider(session, provider_id, **kwargs)
            if not provider:
                raise NotFoundError("供应商配置不存在")
            
            logger.info(f"成功更新供应商配置: id={provider.id}")
            return provider.to_dict(include_sensitive=True)
            
        except ValueError as e:
            logger.warning(f"更新供应商配置失败: {str(e)}")
            raise ValidationError(str(e))
        except Exception as e:
            logger.error(f"更新供应商配置失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"更新供应商配置失败: {str(e)}")
    
    @staticmethod
    async def delete_provider(session: AsyncSession, provider_id: int) -> bool:
        """删除供应商配置"""
        logger.info(f"删除供应商配置: provider_id={provider_id}")
        
        try:
            result = await AsyncProviderMapper.delete_provider(session, provider_id)
            if result:
                logger.info(f"成功删除供应商配置: id={provider_id}")
            return result
            
        except ValueError as e:
            logger.warning(f"删除供应商配置失败: {str(e)}")
            raise ValidationError(str(e))
        except Exception as e:
            logger.error(f"删除供应商配置失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"删除供应商配置失败: {str(e)}")

