"""
异步 LLM 客户端连接池

Semaphore 控制全局 LLM 并发上限，防止打爆 API rate limit。
支持模型自动降级：主模型超时/失败时自动切换到默认模型。
"""
import os
from typing import Optional, Dict, Any
import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

LLM_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "10"))
_llm_semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENCY)


async def acquire_llm_slot():
    """获取 LLM 调用许可（全局最多 LLM_MAX_CONCURRENCY 个并发）"""
    await _llm_semaphore.acquire()


def release_llm_slot():
    """释放 LLM 调用许可"""
    _llm_semaphore.release()


async def _get_default_model_config_id(session: AsyncSession) -> Optional[int]:
    """查询系统默认模型配置 ID（is_default=True 的 ModelInfo 对应的 ModelConfig）"""
    try:
        from sqlalchemy import select
        from app.models.model_config import ModelConfig
        from app.models.model_info import ModelInfo
        stmt = (
            select(ModelConfig.id)
            .join(ModelInfo, ModelConfig.base_model_id == ModelInfo.id)
            .where(ModelInfo.is_default.is_(True), ModelInfo.is_active.is_(True))
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return row
    except Exception as e:
        logger.warning(f"查询默认模型失败: {e}")
        return None


class AsyncLLMPool:
    """异步 LLM 客户端连接池（带模型自动降级）"""
    _clients: Dict[int, Any] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def get_client(cls, model_config_id: int, session: AsyncSession):
        if model_config_id not in cls._clients:
            async with cls._lock:
                if model_config_id not in cls._clients:
                    try:
                        from app.utils.async_llm import get_chatllm_async
                        cls._clients[model_config_id] = await get_chatllm_async(model_config_id, session)
                        logger.info(f"创建异步LLM客户端: model_config_id={model_config_id}")
                    except Exception as e:
                        logger.error(f"创建异步LLM客户端失败: {e}")
                        raise
        return cls._clients[model_config_id]

    @classmethod
    async def get_client_with_fallback(
        cls,
        model_config_id: int,
        session: AsyncSession,
    ):
        """
        获取 LLM 客户端，主模型不可用时自动降级到系统默认模型。
        返回 (client, actually_used_config_id)。
        """
        try:
            client = await cls.get_client(model_config_id, session)
            return client, model_config_id
        except Exception as primary_err:
            logger.warning(f"主模型 config_id={model_config_id} 不可用: {primary_err}，尝试降级")
            fallback_id = await _get_default_model_config_id(session)
            if fallback_id and fallback_id != model_config_id:
                try:
                    client = await cls.get_client(fallback_id, session)
                    logger.info(f"降级成功: {model_config_id} → {fallback_id}")
                    return client, fallback_id
                except Exception as fallback_err:
                    logger.error(f"降级模型也失败: {fallback_err}")
            raise primary_err
    
    @classmethod
    async def clear_cache(cls, model_config_id: Optional[int] = None):
        """
        清除缓存
        
        Args:
            model_config_id: 如果指定，只清除该配置的缓存；否则清除所有
        """
        async with cls._lock:
            if model_config_id:
                if model_config_id in cls._clients:
                    # 关闭客户端连接
                    client = cls._clients[model_config_id]
                    if hasattr(client, '_client') and client._client:
                        await client._client.close()
                    del cls._clients[model_config_id]
                    logger.info(f"清除异步LLM客户端缓存: model_config_id={model_config_id}")
            else:
                # 关闭所有客户端连接
                for client in cls._clients.values():
                    if hasattr(client, '_client') and client._client:
                        await client._client.close()
                cls._clients.clear()
                logger.info("清除所有异步LLM客户端缓存")
    
    @classmethod
    def get_cache_size(cls) -> int:
        """获取当前缓存大小"""
        return len(cls._clients)

