"""
异步 LLM 客户端连接池
使用异步客户端，支持真正的异步调用
"""
from typing import Optional, Dict, Any
import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AsyncLLMPool:
    """异步 LLM 客户端连接池"""
    _clients: Dict[int, Any] = {}
    _lock = asyncio.Lock()
    
    @classmethod
    async def get_client(cls, model_config_id: int, session: AsyncSession):
        """
        获取或创建异步 LLM 客户端
        
        Args:
            model_config_id: 模型配置ID
            session: 异步数据库会话
        
        Returns:
            异步 LLM 客户端实例
        """
        if model_config_id not in cls._clients:
            async with cls._lock:
                # 双重检查锁定
                if model_config_id not in cls._clients:
                    try:
                        from app.utils.async_llm import get_chatllm_async
                        cls._clients[model_config_id] = await get_chatllm_async(model_config_id, session)
                        logger.info(f"创建新的异步LLM客户端: model_config_id={model_config_id}")
                    except Exception as e:
                        logger.error(f"创建异步LLM客户端失败: {e}")
                        raise
        return cls._clients[model_config_id]
    
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

