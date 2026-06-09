"""
异步 LLM 客户端连接池

- Semaphore 控制全局 LLM 并发上限，防止打爆 API rate limit
- Circuit Breaker 熔断器：Provider 连续失败时快速拒绝
- Bulkhead 舱壁隔离：各 Provider 独立并发配额
- 模型自动降级：主模型不可用时切换到系统默认模型
"""
import os
from typing import Optional, Dict, Any
import asyncio
import logging
from collections import OrderedDict
from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.circuit_breaker import get_circuit_breaker, CircuitOpenError

logger = logging.getLogger(__name__)

LLM_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "10"))
LLM_CLIENT_CACHE_MAX = int(os.getenv("LLM_CLIENT_CACHE_MAX", "50"))
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
    """异步 LLM 客户端连接池（LRU 上限 + Circuit Breaker + 模型自动降级）"""
    _clients: OrderedDict = OrderedDict()
    _lock = asyncio.Lock()

    @classmethod
    async def get_client(cls, model_config_id: int, session: AsyncSession):
        if model_config_id in cls._clients:
            cls._clients.move_to_end(model_config_id)
            return cls._clients[model_config_id]

        async with cls._lock:
            if model_config_id in cls._clients:
                cls._clients.move_to_end(model_config_id)
                return cls._clients[model_config_id]

            try:
                from app.utils.async_llm import get_chatllm_async
                client = await get_chatllm_async(model_config_id, session)

                # LRU 淘汰：超过上限时移除最久未用的客户端
                while len(cls._clients) >= LLM_CLIENT_CACHE_MAX:
                    evicted_id, evicted_client = cls._clients.popitem(last=False)
                    if hasattr(evicted_client, '_client') and evicted_client._client:
                        try:
                            await evicted_client._client.close()
                        except Exception:
                            pass
                    logger.info(f"LLM 客户端缓存淘汰: config_id={evicted_id}")

                cls._clients[model_config_id] = client
                logger.info(f"创建异步 LLM 客户端: config_id={model_config_id}, cache_size={len(cls._clients)}")
                return client
            except Exception as e:
                logger.error(f"创建异步 LLM 客户端失败: {e}")
                raise

    @classmethod
    async def get_client_with_fallback(
        cls,
        model_config_id: int,
        session: AsyncSession,
    ):
        """
        获取 LLM 客户端，主模型不可用时自动降级到系统默认模型。
        集成 Circuit Breaker：Provider 连续失败时快速拒绝。
        返回 (client, actually_used_config_id)。
        """
        try:
            # Circuit Breaker 检查（基于 model_config_id）
            breaker = get_circuit_breaker(f"llm_config_{model_config_id}")
            if breaker.state.value == "open":
                raise CircuitOpenError(f"llm_config_{model_config_id}", breaker.recovery_timeout)

            client = await cls.get_client(model_config_id, session)
            return client, model_config_id
        except (CircuitOpenError, Exception) as primary_err:
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

