"""
检索模块
支持向量检索（ChromaDB）和混合检索（向量 + BM25，RRF 融合）
"""
import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from collections import OrderedDict
from app.utils.logger_config import get_logger

logger = get_logger(__name__)

# 启动时检测 jieba 是否可用
_HAS_JIEBA = False
try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    logger.warning("jieba 未安装，BM25 分词将降级为字符 n-gram，检索质量会下降")

_STOPWORDS = frozenset({
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "被",
    "从", "把", "对", "与", "为", "之", "其", "而", "及", "以", "或",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "of", "in", "to", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "but",
    "not", "or", "and", "if", "this", "that", "it", "he", "she", "they",
})
_PUNCT_RE = re.compile(r'[^\w\s]', re.UNICODE)

# BM25 内存缓存（LRU，最多缓存 20 个知识库的索引，带 TTL）
_BM25_CACHE: "OrderedDict[int, Any]" = OrderedDict()
_BM25_CACHE_MAX = 20
_BM25_CACHE_TTL = 600  # 10 分钟过期


# ------------------------------------------------------------------
# 距离 → 相似度转换
# ------------------------------------------------------------------

def _detect_distance_fn(collection) -> str:
    """从 ChromaDB collection 的 metadata 中检测距离函数类型"""
    try:
        meta = getattr(collection, 'metadata', None) or {}
        return (meta.get('hnsw:space') or 'l2').lower()
    except Exception:
        return 'l2'


def _distance_to_similarity(distance: float, dist_fn: str) -> float:
    """
    根据距离函数类型将 ChromaDB 返回的 distance 转换为 [0, 1] 范围的相似度。

    - cosine : ChromaDB cosine distance = 1 - cosine_similarity ∈ [0, 2]
               similarity = 1 - distance, clamp 到 [0, 1]
    - l2     : 欧氏距离 ∈ [0, +∞)
               similarity = 1 / (1 + distance), 映射到 (0, 1]
    - ip     : 内积距离（负内积），越小越相似
               similarity = 1 / (1 + max(0, distance))
    """
    if dist_fn == 'cosine':
        return max(0.0, min(1.0, 1.0 - distance))
    elif dist_fn == 'ip':
        return 1.0 / (1.0 + max(0.0, distance))
    else:
        # L2 / 未知类型：用 1/(1+d) 保证结果在 (0, 1]
        return 1.0 / (1.0 + max(0.0, distance))


# ------------------------------------------------------------------
# 数据结构
# ------------------------------------------------------------------

@dataclass
class RetrievalResult:
    """检索结果数据类"""
    chunk_id: str
    content: str
    score: float             # 最终融合分数
    vector_score: float = 0.0
    bm25_score: float = 0.0
    similarity: float = 0.0  # 归一化综合相似度 [0, 1]，用于展示和阈值判断
    source: str = ""
    document_id: str = ""
    rerank_score: float = 0.0
    retrieval_method: str = "vector"  # "vector" | "bm25" | "hybrid" | "hybrid+rerank"
    metadata: Dict = field(default_factory=dict)


def _dedup_by_document(results: List[RetrievalResult]) -> List[RetrievalResult]:
    """
    去重：Parent-Child 策略按 (document_id, parent_index) 去重（保留同文档不同 parent），
    普通策略按 document_id 去重。保持原有排序（按 score 降序）。
    """
    best: Dict[str, RetrievalResult] = {}
    for r in results:
        parent_idx = r.metadata.get('parent_index')
        if parent_idx is not None:
            doc_key = f"{r.document_id}_p{parent_idx}"
        else:
            doc_key = r.document_id or r.chunk_id
        if doc_key not in best or r.score > best[doc_key].score:
            best[doc_key] = r
    seen = set()
    deduped = []
    for r in results:
        parent_idx = r.metadata.get('parent_index')
        if parent_idx is not None:
            doc_key = f"{r.document_id}_p{parent_idx}"
        else:
            doc_key = r.document_id or r.chunk_id
        if doc_key not in seen and best.get(doc_key) is r:
            deduped.append(r)
            seen.add(doc_key)
    return deduped


# ------------------------------------------------------------------
# 主检索类
# ------------------------------------------------------------------

class VectorRetriever:
    """
    向量检索器（Phase 1：仅向量检索）
    Phase 2 将在此基础上添加 BM25 混合检索。
    """

    # ---- 向量检索 ----

    @staticmethod
    async def query(
        vector_db_id: int,
        query_text: str,
        n_results: int = 5,
        folder_path: Optional[str] = None,
        parent_id: Optional[int] = None,
    ) -> List[RetrievalResult]:
        """
        向量相似度检索。

        Args:
            vector_db_id: 知识库 ID
            query_text: 查询文本
            n_results: 返回结果数量
            folder_path: 可选的文件夹路径过滤
            parent_id: 可选的父文件夹 ID 过滤

        Returns:
            RetrievalResult 列表
        """
        from app.utils.optimized_chromadb import get_chromadb_client
        from app.utils.async_embedding import get_query_embedding_async

        client = get_chromadb_client()
        if not client:
            raise RuntimeError("ChromaDB 服务不可用，请检查 ChromaDB 是否已启动（默认端口 8000）")

        collection_name = f"vector_db_{vector_db_id}"
        try:
            collection = await asyncio.to_thread(client.get_collection, name=collection_name)
        except Exception as e:
            logger.warning(f"获取集合失败 {collection_name}: {e}")
            raise RuntimeError(f"知识库向量集合不存在或不可用: {collection_name}")

        try:
            query_embedding = await get_query_embedding_async(query_text)

            where: Optional[Dict] = None
            if folder_path or parent_id:
                where = {}
                if folder_path:
                    where['folder_hierarchy'] = folder_path
                if parent_id:
                    where['parent_id'] = str(parent_id)

            kwargs: Dict[str, Any] = {
                'query_embeddings': [query_embedding],
                'n_results': n_results,
            }
            if where:
                kwargs['where'] = where

            results = await asyncio.to_thread(collection.query, **kwargs)

            dist_fn = _detect_distance_fn(collection)

            output = []
            if results.get('documents') and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    distance = results['distances'][0][i] if results.get('distances') else 0.0
                    chunk_id = results['ids'][0][i] if results.get('ids') else str(i)
                    meta = (results['metadatas'][0][i] if results.get('metadatas') else {}) or {}
                    similarity = _distance_to_similarity(distance, dist_fn)
                    # Parent-Child: child 匹配但返回 parent 内容给 LLM
                    content = meta.get('parent_content') or doc
                    output.append(RetrievalResult(
                        chunk_id=chunk_id,
                        content=content,
                        score=similarity,
                        vector_score=similarity,
                        similarity=similarity,
                        source=meta.get('source', ''),
                        document_id=str(meta.get('document_id', '')),
                        retrieval_method='vector',
                        metadata=meta,
                    ))
            return _dedup_by_document(output)
        except Exception as e:
            logger.error(f"向量检索失败 {collection_name}: {e}", exc_info=True)
            return []

    # ---- 混合检索（BM25 + 向量，RRF 融合）----

    @staticmethod
    async def hybrid_query(
        vector_db_id: int,
        query_text: str,
        n_results: int = 10,
        alpha: float = 0.7,
        folder_path: Optional[str] = None,
        parent_id: Optional[int] = None,
    ) -> List[RetrievalResult]:
        """
        混合检索：向量检索 + BM25 关键词检索，RRF 算法融合。

        Args:
            vector_db_id: 知识库 ID
            query_text: 查询文本
            n_results: 最终返回数量
            alpha: 向量分数权重（0-1），1-alpha 为 BM25 权重
            folder_path: 可选的文件夹路径过滤
            parent_id: 可选的父文件夹 ID 过滤

        Returns:
            RetrievalResult 列表（按 RRF 融合分数降序）
        """
        # 并发执行向量检索 + BM25 检索
        vector_task = VectorRetriever.query(
            vector_db_id, query_text, n_results * 2, folder_path, parent_id
        )
        bm25_task = VectorRetriever._bm25_query(
            vector_db_id, query_text, n_results * 2
        )
        vector_results, bm25_results = await asyncio.gather(vector_task, bm25_task)

        if not bm25_results:
            # BM25 不可用时降级为纯向量
            for r in vector_results:
                r.retrieval_method = 'vector'
            return vector_results[:n_results]

        merged = VectorRetriever._rrf_merge(vector_results, bm25_results, alpha, n_results)
        return _dedup_by_document(merged)

    @staticmethod
    async def _bm25_query(
        vector_db_id: int,
        query_text: str,
        n_results: int,
    ) -> List[RetrievalResult]:
        """BM25 关键词检索（内存缓存 BM25 索引）"""
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("rank-bm25 未安装，BM25 检索不可用")
            return []

        # 构建 / 获取 BM25 索引
        index_data = await VectorRetriever._get_bm25_index(vector_db_id)
        if not index_data:
            return []

        bm25: BM25Okapi = index_data['bm25']
        chunk_ids: List[str] = index_data['chunk_ids']
        contents: List[str] = index_data['contents']
        metas: List[Dict] = index_data['metas']

        # 分词（简单空格 + jieba 分词）
        tokens = VectorRetriever._tokenize(query_text)
        scores = bm25.get_scores(tokens)

        # 取 top-k
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n_results]
        results = []
        max_score = max(scores[i] for i in top_indices) if top_indices else 1.0
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            normalized = scores[idx] / max_score if max_score > 0 else 0.0
            meta = metas[idx]
            # Parent-Child: child 匹配但返回 parent 内容给 LLM
            content = meta.get('parent_content') or contents[idx]
            results.append(RetrievalResult(
                chunk_id=chunk_ids[idx],
                content=content,
                score=normalized,
                bm25_score=normalized,
                similarity=normalized,
                source=meta.get('source', ''),
                document_id=str(meta.get('document_id', '')),
                retrieval_method='bm25',
                metadata=meta,
            ))
        return results

    @staticmethod
    async def _get_bm25_index(vector_db_id: int) -> Optional[Dict]:
        """
        获取（或构建）BM25 索引，进程内 LRU 缓存，带 TTL 过期。
        文档变更后应调用 invalidate_bm25_cache(vector_db_id) 清除缓存。
        """
        if vector_db_id in _BM25_CACHE:
            cached = _BM25_CACHE[vector_db_id]
            if time.monotonic() - cached.get('_created_at', 0) < _BM25_CACHE_TTL:
                _BM25_CACHE.move_to_end(vector_db_id)
                return cached
            del _BM25_CACHE[vector_db_id]

        # 从 ChromaDB 加载所有文本
        from app.utils.optimized_chromadb import get_chromadb_client
        from rank_bm25 import BM25Okapi

        client = get_chromadb_client()
        if not client:
            return None

        collection_name = f"vector_db_{vector_db_id}"
        try:
            collection = await asyncio.to_thread(client.get_collection, name=collection_name)
            data = await asyncio.to_thread(
                collection.get,
                include=['documents', 'metadatas']
            )
        except Exception as e:
            logger.error(f"BM25 索引构建失败，无法获取集合 {collection_name}: {e}")
            return None

        docs = data.get('documents') or []
        metas = data.get('metadatas') or [{}] * len(docs)
        ids = data.get('ids') or [str(i) for i in range(len(docs))]

        if not docs:
            return None

        tokenized = [VectorRetriever._tokenize(d) for d in docs]
        bm25 = BM25Okapi(tokenized)

        index_data = {
            'bm25': bm25,
            'chunk_ids': ids,
            'contents': docs,
            'metas': metas,
            '_created_at': time.monotonic(),
        }

        # LRU 缓存
        if len(_BM25_CACHE) >= _BM25_CACHE_MAX:
            _BM25_CACHE.popitem(last=False)
        _BM25_CACHE[vector_db_id] = index_data
        logger.info(f"BM25 索引构建完成: vector_db_id={vector_db_id}, {len(docs)} 个 chunk")
        return index_data

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """分词：jieba 分词 + 停用词/标点过滤，降级为字符 bigram"""
        text = _PUNCT_RE.sub(' ', text).lower().strip()
        if not text:
            return []
        if _HAS_JIEBA:
            tokens = list(jieba.cut(text))
        else:
            # 降级：字符 bigram 而非单字符，保留基本语义
            tokens = [text[i:i+2] for i in range(len(text) - 1)] if len(text) > 1 else [text]
        return [t.strip() for t in tokens if t.strip() and t.strip() not in _STOPWORDS]

    @staticmethod
    def _rrf_merge(
        vector_results: List[RetrievalResult],
        bm25_results: List[RetrievalResult],
        alpha: float,
        n_results: int,
        k: int = 60,
    ) -> List[RetrievalResult]:
        """
        Reciprocal Rank Fusion (RRF) 融合两路检索结果。
        RRF score = alpha * 1/(k + rank_v) + (1-alpha) * 1/(k + rank_b)
        """
        # chunk_id → result 索引
        vector_map = {r.chunk_id: (rank, r) for rank, r in enumerate(vector_results)}
        bm25_map = {r.chunk_id: (rank, r) for rank, r in enumerate(bm25_results)}

        all_ids = set(vector_map.keys()) | set(bm25_map.keys())
        fused: List[RetrievalResult] = []

        for cid in all_ids:
            v_rank, v_res = vector_map.get(cid, (len(vector_results), None))
            b_rank, b_res = bm25_map.get(cid, (len(bm25_results), None))

            rrf_score = alpha / (k + v_rank) + (1 - alpha) / (k + b_rank)

            v_score = v_res.vector_score if v_res else 0.0
            b_score = b_res.bm25_score if b_res else 0.0
            similarity = alpha * v_score + (1 - alpha) * b_score

            base = v_res or b_res
            result = RetrievalResult(
                chunk_id=cid,
                content=base.content,
                score=rrf_score,
                vector_score=v_score,
                bm25_score=b_score,
                similarity=similarity,
                source=base.source,
                document_id=base.document_id,
                retrieval_method='hybrid',
                metadata=base.metadata,
            )
            fused.append(result)

        fused.sort(key=lambda r: r.score, reverse=True)
        return fused[:n_results]

    # ---- 增强检索：Query 改写 + HyDE + 混合检索 + Reranker 精排 ----

    @staticmethod
    async def enhanced_query(
        vector_db_id: int,
        query_text: str,
        n_results: int = 5,
        alpha: float = 0.7,
        use_rewrite: bool = True,
        use_rerank: bool = True,
        use_hyde: bool = False,
        folder_path: Optional[str] = None,
        parent_id: Optional[int] = None,
    ) -> List[RetrievalResult]:
        """
        增强检索管线：Query 改写 → (可选)HyDE → 多路混合检索 → RRF 融合 → Reranker 精排
        """
        queries = [query_text]
        if use_rewrite:
            try:
                from app.services.rag.query_rewriter import rewrite_query
                queries = await rewrite_query(query_text, n_rewrites=3)
            except Exception as e:
                logger.warning(f"Query 改写失败，使用原始 query: {e}")

        hyde_text = None
        if use_hyde:
            try:
                from app.services.rag.query_rewriter import hyde_rewrite
                hyde_text = await hyde_rewrite(query_text)
            except Exception as e:
                logger.warning(f"HyDE 生成失败: {e}")

        coarse_n = n_results * 4 if use_rerank else n_results

        retrieval_tasks = [
            VectorRetriever.hybrid_query(
                vector_db_id, q, coarse_n, alpha, folder_path, parent_id,
            )
            for q in queries
        ]
        if hyde_text:
            retrieval_tasks.append(
                VectorRetriever.query(
                    vector_db_id, hyde_text, coarse_n, folder_path, parent_id,
                )
            )

        multi_results = await asyncio.gather(*retrieval_tasks)

        seen_chunks = set()
        all_results: List[RetrievalResult] = []
        for results in multi_results:
            for r in results:
                if r.chunk_id not in seen_chunks:
                    all_results.append(r)
                    seen_chunks.add(r.chunk_id)

        all_results.sort(key=lambda r: r.score, reverse=True)
        coarse_results = all_results[:coarse_n]

        if use_rerank and len(coarse_results) > n_results:
            try:
                from app.services.rag.reranker import rerank
                final_results = await rerank(query_text, coarse_results, top_k=n_results)
            except Exception as e:
                logger.warning(f"Reranker 失败，降级为粗排: {e}")
                final_results = coarse_results[:n_results]
        else:
            final_results = coarse_results[:n_results]

        return _dedup_by_document(final_results)


# ------------------------------------------------------------------
# 缓存失效接口（文档变更时调用）
# ------------------------------------------------------------------

def invalidate_bm25_cache(vector_db_id: int) -> None:
    """使指定知识库的 BM25 索引缓存失效"""
    if vector_db_id in _BM25_CACHE:
        del _BM25_CACHE[vector_db_id]
        logger.info(f"BM25 缓存已失效: vector_db_id={vector_db_id}")
