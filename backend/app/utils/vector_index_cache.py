"""
向量索引缓存 — Size-Aware LRU + Memory Pressure 监控

- 按内存大小（非数量）淘汰：大索引占更多配额
- 全局上限 512MB，可通过环境变量 INDEX_CACHE_MAX_MB 配置
- 内存使用超 85% 时主动淘汰一半缓存
"""
import os
import sys
from typing import Optional, Dict, Any
from collections import OrderedDict
from threading import Lock
import logging
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore

logger = logging.getLogger(__name__)

_INDEX_CACHE_MAX_BYTES = int(os.getenv("INDEX_CACHE_MAX_MB", "512")) * 1024 * 1024


class SizeAwareLRU:
    """按内存大小淘汰的 LRU 缓存。"""

    def __init__(self, max_bytes: int):
        self._cache: OrderedDict = OrderedDict()
        self._sizes: Dict[Any, int] = {}
        self._total_bytes: int = 0
        self._max_bytes: int = max_bytes
        self._hits: int = 0
        self._misses: int = 0

    def get(self, key):
        if key in self._cache:
            self._cache.move_to_end(key)
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        return None

    def put(self, key, value, size_bytes: int):
        if key in self._cache:
            self._total_bytes -= self._sizes[key]
            del self._cache[key]

        while self._total_bytes + size_bytes > self._max_bytes and self._cache:
            evicted_key, _ = self._cache.popitem(last=False)
            evicted_size = self._sizes.pop(evicted_key)
            self._total_bytes -= evicted_size
            logger.info(f"索引缓存淘汰: key={evicted_key}, freed={evicted_size / 1024 / 1024:.1f}MB")

        self._cache[key] = value
        self._sizes[key] = size_bytes
        self._total_bytes += size_bytes

    def remove(self, key):
        if key in self._cache:
            self._total_bytes -= self._sizes.pop(key)
            del self._cache[key]

    def clear(self):
        self._cache.clear()
        self._sizes.clear()
        self._total_bytes = 0

    def evict_half(self):
        count = len(self._cache) // 2
        for _ in range(count):
            if self._cache:
                k, _ = self._cache.popitem(last=False)
                self._total_bytes -= self._sizes.pop(k, 0)
        return count

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "entries": len(self._cache),
            "total_mb": round(self._total_bytes / 1024 / 1024, 1),
            "max_mb": round(self._max_bytes / 1024 / 1024, 1),
            "hit_rate": round(self._hits / max(1, total), 3),
            "hits": self._hits,
            "misses": self._misses,
        }


_index_cache = SizeAwareLRU(_INDEX_CACHE_MAX_BYTES)
_embedding_model_cache: Optional[object] = None
_cache_lock = Lock()


def _estimate_index_size(index: VectorStoreIndex) -> int:
    """粗略估算索引对象的内存占用（取 sys.getsizeof 的 10 倍作为保守估计）。"""
    try:
        base = sys.getsizeof(index)
        return max(base * 10, 10 * 1024 * 1024)  # 最少 10MB
    except Exception:
        return 50 * 1024 * 1024  # 默认 50MB


def check_memory_pressure():
    """内存使用超 85% 时主动淘汰一半缓存。"""
    try:
        import psutil
        mem = psutil.virtual_memory()
        if mem.percent > 85:
            evicted = _index_cache.evict_half()
            logger.warning(f"内存压力 ({mem.percent}%): 紧急淘汰 {evicted} 个索引")
    except ImportError:
        pass
    except Exception as e:
        logger.error(f"内存压力检查失败: {e}")


def get_embedding_model():
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
    cached = _index_cache.get(vector_db_id)
    if cached is not None:
        return cached

    with _cache_lock:
        cached = _index_cache.get(vector_db_id)
        if cached is not None:
            return cached

        try:
            from app.services.vector_service import AsyncVectorService
            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        chroma_collection = pool.submit(
                            asyncio.run,
                            AsyncVectorService.get_chroma_collection(vector_db_id)
                        ).result()
                else:
                    chroma_collection = loop.run_until_complete(
                        AsyncVectorService.get_chroma_collection(vector_db_id)
                    )
            except RuntimeError:
                chroma_collection = asyncio.run(
                    AsyncVectorService.get_chroma_collection(vector_db_id)
                )

            if not chroma_collection:
                logger.error(f"无法获取 ChromaDB 集合: vector_db_{vector_db_id}")
                return None

            vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
            embedding_model = get_embedding_model()
            index = VectorStoreIndex.from_vector_store(
                vector_store=vector_store,
                embed_model=embedding_model
            )

            size = _estimate_index_size(index)
            _index_cache.put(vector_db_id, index, size)
            logger.info(
                f"向量索引已缓存: vector_db_{vector_db_id}, "
                f"size≈{size / 1024 / 1024:.0f}MB, {_index_cache.stats}"
            )

            check_memory_pressure()
            return index

        except Exception as e:
            logger.error(f"创建向量索引失败: {e}")
            return None


def clear_index_cache(vector_db_id: Optional[int] = None):
    with _cache_lock:
        if vector_db_id:
            _index_cache.remove(vector_db_id)
            logger.info(f"清除向量索引缓存: vector_db_{vector_db_id}")
        else:
            _index_cache.clear()
            logger.info("清除所有向量索引缓存")


def get_cache_stats() -> dict:
    return _index_cache.stats
