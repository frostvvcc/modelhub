"""
异步嵌入模型工具
"""
from typing import List, Optional
import asyncio
import logging
from app.config import settings
from app.utils.EmbbedingModel import ChatEmbeddings

logger = logging.getLogger(__name__)

# 全局嵌入模型实例（单例）
_embedding_model: Optional[ChatEmbeddings] = None
_embedding_lock = asyncio.Lock()


async def get_embedding_model_async() -> ChatEmbeddings:
    """异步获取嵌入模型（单例）"""
    global _embedding_model
    
    if _embedding_model is None:
        async with _embedding_lock:
            if _embedding_model is None:
                # 在后台线程创建（因为 ChatEmbeddings 可能是同步的）
                _embedding_model = await asyncio.to_thread(
                    lambda: ChatEmbeddings(
                        model=settings.embedding_model,
                        base_url=settings.embedding_base_url,
                        api_key=settings.embedding_api_key
                    )
                )
                logger.info("异步嵌入模型已创建")
    
    return _embedding_model


async def get_query_embedding_async(query_text: str) -> List[float]:
    """异步获取查询文本的嵌入向量（input_type=query）"""
    try:
        model = await get_embedding_model_async()
        embedding = await asyncio.to_thread(
            model.get_general_text_embedding, query_text, "query",
        )
        return embedding
    except Exception as e:
        logger.error(f"获取查询嵌入失败: {e}")
        raise


async def get_text_embeddings_async(texts: List[str]) -> List[List[float]]:
    """异步获取多个文档文本的嵌入向量（input_type=document）"""
    try:
        model = await get_embedding_model_async()
        embeddings = await asyncio.to_thread(
            model.get_text_embeddings, texts,
        )
        return embeddings
    except Exception as e:
        logger.error(f"获取文本嵌入失败: {e}")
        raise

