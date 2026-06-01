"""
向量索引缓存
缓存向量索引和嵌入模型，避免重复创建
"""
from typing import Optional, Dict
from threading import Lock
import logging
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore

logger = logging.getLogger(__name__)

# 索引缓存
_index_cache: Dict[int, VectorStoreIndex] = {}
_embedding_model_cache: Optional[object] = None
_cache_lock = Lock()

def get_embedding_model():
    """
    获取或创建嵌入模型（单例）
    """
    global _embedding_model_cache
    
    if _embedding_model_cache is None:
        with _cache_lock:
            if _embedding_model_cache is None:
                from app.utils.EmbbedingModel import ChatEmbeddings
                from app.config import settings
                
                _embedding_model_cache = ChatEmbeddings(
                    model=settings.embedding_model,
                    base_url=settings.embedding_base_url,
                    api_key=settings.embedding_api_key
                )
                logger.info("嵌入模型已创建并缓存")
    
    return _embedding_model_cache

def get_or_create_index(vector_db_id: int) -> Optional[VectorStoreIndex]:
    """
    获取或创建向量索引
    
    :param vector_db_id: 向量数据库ID
    :return: VectorStoreIndex实例
    """
    if vector_db_id not in _index_cache:
        with _cache_lock:
            # 双重检查
            if vector_db_id not in _index_cache:
                try:
                    from app.services.vector_service import AsyncVectorService
                    
                    # 获取ChromaDB集合（需要同步调用，因为这是同步函数）
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        chroma_collection = loop.run_until_complete(
                            AsyncVectorService.get_chroma_collection(vector_db_id)
                        )
                    except RuntimeError:
                        # 如果没有事件循环，创建新的
                        chroma_collection = asyncio.run(
                            AsyncVectorService.get_chroma_collection(vector_db_id)
                        )
                    if not chroma_collection:
                        logger.error(f"无法获取ChromaDB集合: vector_db_{vector_db_id}")
                        return None
                    
                    # 创建向量存储
                    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
                    
                    # 获取嵌入模型
                    embedding_model = get_embedding_model()
                    
                    # 创建索引
                    index = VectorStoreIndex.from_vector_store(
                        vector_store=vector_store,
                        embed_model=embedding_model
                    )
                    
                    _index_cache[vector_db_id] = index
                    logger.info(f"向量索引已创建并缓存: vector_db_{vector_db_id}")
                    
                except Exception as e:
                    logger.error(f"创建向量索引失败: {e}")
                    return None
    
    return _index_cache.get(vector_db_id)

def clear_index_cache(vector_db_id: Optional[int] = None):
    """
    清除索引缓存
    
    :param vector_db_id: 如果指定，只清除该索引；否则清除所有
    """
    global _index_cache
    with _cache_lock:
        if vector_db_id:
            if vector_db_id in _index_cache:
                del _index_cache[vector_db_id]
                logger.info(f"清除向量索引缓存: vector_db_{vector_db_id}")
        else:
            _index_cache.clear()
            logger.info("清除所有向量索引缓存")

