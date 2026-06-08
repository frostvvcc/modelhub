"""
检索模块
支持向量检索（ChromaDB）和混合检索（向量 + BM25，RRF 融合）
"""
import asyncio
import math
import os
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


def _sigmoid_normalize(raw_score: float, k: float = 10.0) -> float:
    """BM25 原始分数 → [0, 1] sigmoid 归一化，保留绝对语义"""
    return 1.0 / (1.0 + math.exp(-raw_score / k))


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


_MMR_LAMBDA = float(os.getenv("RAG_MMR_LAMBDA", "0.7"))


def _jaccard_ngram(a: str, b: str, n: int = 3) -> float:
    if len(a) < n or len(b) < n:
        return 1.0 if a == b else 0.0
    set_a = set(a[i:i+n] for i in range(len(a) - n + 1))
    set_b = set(b[i:i+n] for i in range(len(b) - n + 1))
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def _mmr_diversify(
    results: List[RetrievalResult],
    n_results: int,
    lambda_param: float = _MMR_LAMBDA,
) -> List[RetrievalResult]:
    """
    MMR (Maximal Marginal Relevance) 多样性重排。
    在相关性和多样性之间取平衡，避免返回内容高度重复的 chunk。
    lambda=1.0 纯相关性；lambda=0.0 最大多样性。
    """
    if len(results) <= n_results:
        return results

    selected: List[RetrievalResult] = []
    candidates = list(results)

    selected.append(candidates.pop(0))

    while len(selected) < n_results and candidates:
        best_idx, best_mmr = -1, -float('inf')
        for i, cand in enumerate(candidates):
            relevance = cand.score
            max_sim = max(
                _jaccard_ngram(cand.content, s.content) for s in selected
            )
            mmr = lambda_param * relevance - (1 - lambda_param) * max_sim
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = i
        if best_idx >= 0:
            selected.append(candidates.pop(best_idx))
        else:
            break

    return selected


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
        metadata_filter: Optional[Dict] = None,
    ) -> List[RetrievalResult]:
        """
        向量相似度检索。

        Args:
            vector_db_id: 知识库 ID
            query_text: 查询文本
            n_results: 返回结果数量
            folder_path: 可选的文件夹路径过滤
            parent_id: 可选的父文件夹 ID 过滤
            metadata_filter: 结构化约束过滤（年份、院系等），直接传给 ChromaDB where

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

            # 合并文件夹过滤和结构化约束过滤
            where_conditions = []
            if folder_path:
                where_conditions.append({'folder_hierarchy': folder_path})
            if parent_id:
                where_conditions.append({'parent_id': str(parent_id)})
            if metadata_filter:
                if "$and" in metadata_filter:
                    where_conditions.extend(metadata_filter["$and"])
                else:
                    where_conditions.append(metadata_filter)

            where: Optional[Dict] = None
            if len(where_conditions) == 1:
                where = where_conditions[0]
            elif len(where_conditions) > 1:
                where = {"$and": where_conditions}

            # 带约束过滤的检索 + 渐进式放宽策略
            kwargs: Dict[str, Any] = {
                'query_embeddings': [query_embedding],
                'n_results': n_results,
            }
            if where:
                kwargs['where'] = where

            results = await asyncio.to_thread(collection.query, **kwargs)

            doc_count = len(results.get('documents', [[]])[0]) if results.get('documents') else 0
            if where and doc_count < 1:
                    logger.info(f"过滤后无结果，放宽为无条件检索")
                    fallback_kwargs = {
                        'query_embeddings': [query_embedding],
                        'n_results': n_results,
                    }
                    results = await asyncio.to_thread(collection.query, **fallback_kwargs)

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
            output = [r for r in output if r.vector_score >= 0.35]
            return _mmr_diversify(output, n_results)
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
        metadata_filter: Optional[Dict] = None,
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
            metadata_filter: 结构化约束过滤（年份、院系等）

        Returns:
            RetrievalResult 列表（按 RRF 融合分数降序）
        """
        # 并发执行向量检索 + BM25 检索
        vector_task = VectorRetriever.query(
            vector_db_id, query_text, n_results * 2, folder_path, parent_id,
            metadata_filter=metadata_filter,
        )
        bm25_task = VectorRetriever._bm25_query(
            vector_db_id, query_text, n_results * 2,
            metadata_filter=metadata_filter,
        )
        _t0 = time.perf_counter()
        vector_results, bm25_results = await asyncio.gather(vector_task, bm25_task)
        _bm25_ms = (time.perf_counter() - _t0) * 1000

        logger.info(
            f"🔍 [混合检索] vector_db_id={vector_db_id}: "
            f"向量={len(vector_results)}条, BM25={len(bm25_results)}条"
        )

        merged = VectorRetriever._rrf_merge(vector_results, bm25_results, alpha, n_results)
        return _mmr_diversify(merged, n_results)

    @staticmethod
    async def _bm25_query(
        vector_db_id: int,
        query_text: str,
        n_results: int,
        metadata_filter: Optional[Dict] = None,
    ) -> List[RetrievalResult]:
        """BM25 关键词检索：优先 Elasticsearch，降级为内存 BM25"""
        # 优先使用 Elasticsearch（分布式、支持大规模知识库）
        try:
            from app.services.rag.es_retrieval import ES_ENABLED, search as es_search
            if ES_ENABLED:
                es_results = await es_search(
                    vector_db_id, query_text, n_results,
                    metadata_filter=metadata_filter,
                )
                if es_results:
                    return [
                        RetrievalResult(
                            chunk_id=r["chunk_id"],
                            content=r["content"],
                            score=_sigmoid_normalize(r["score"]),
                            bm25_score=_sigmoid_normalize(r["score"]),
                            similarity=_sigmoid_normalize(r["score"]),
                            source=r.get("source", ""),
                            document_id=r.get("document_id", ""),
                            retrieval_method="bm25_es",
                        )
                        for r in es_results
                    ]
        except Exception as es_err:
            logger.warning(f"Elasticsearch 检索失败，降级为内存 BM25: {es_err}")

        # 降级：内存 BM25（使用 BM25L，IDF 始终非负，小语料库不会产生负分）
        try:
            from rank_bm25 import BM25L
        except ImportError:
            logger.warning("rank-bm25 未安装，BM25 检索不可用")
            return []

        index_data = await VectorRetriever._get_bm25_index(vector_db_id)
        if not index_data:
            logger.warning(f"BM25 内存索引为空: vector_db_id={vector_db_id}，BM25 检索不可用（ChromaDB 集合可能为空或不可达）")
            return []

        bm25 = index_data["bm25"]
        chunk_ids: List[str] = index_data['chunk_ids']
        contents: List[str] = index_data['contents']
        metas: List[Dict] = index_data['metas']

        # 分词（简单空格 + jieba 分词）
        tokens = VectorRetriever._tokenize(query_text)
        scores = bm25.get_scores(tokens)

        # 取 top-k
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n_results]
        results = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            normalized = _sigmoid_normalize(scores[idx])
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
        from rank_bm25 import BM25L

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
        metas = data.get('metadatas') or [{} for _ in range(len(docs))]
        ids = data.get('ids') or [str(i) for i in range(len(docs))]

        if not docs:
            return None

        tokenized = [VectorRetriever._tokenize(d) for d in docs]
        bm25 = BM25L(tokenized)

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
        """分词：jieba 搜索模式分词 + 停用词/标点过滤，降级为字符 bigram"""
        text = _PUNCT_RE.sub(' ', text).lower().strip()
        if not text:
            return []
        if _HAS_JIEBA:
            tokens = list(jieba.cut_for_search(text))
        else:
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
        penalty = max(len(vector_results), len(bm25_results), n_results)

        all_ids = set(vector_map.keys()) | set(bm25_map.keys())
        fused: List[RetrievalResult] = []

        for cid in all_ids:
            v_rank, v_res = vector_map.get(cid, (penalty, None))
            b_rank, b_res = bm25_map.get(cid, (penalty, None))

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

        # 质量过滤：BM25 有实质匹配（sigmoid > 0.5）或向量相似度达标
        filtered = [r for r in fused if r.bm25_score > 0.5 or r.vector_score >= 0.35]
        return filtered[:n_results] if filtered else fused[:1]

    # ---- 查询准备（LLM 调用，只需执行一次）----

    @dataclass
    class PreparedQuery:
        """查询准备结果：所有 LLM 调用的产物，可跨多个知识库复用。"""
        original_query: str
        queries: list
        hyde_text: Optional[str]
        constraints: Any
        metadata_filter: Optional[dict]
        use_rerank: bool
        use_graph: bool
        coarse_n: int

    @staticmethod
    async def prepare_query(
        query_text: str,
        n_results: int = 5,
        use_rewrite: bool = True,
        use_rerank: bool = True,
        use_hyde: bool = False,
        use_graph: bool = True,
    ) -> "VectorRetriever.PreparedQuery":
        """
        查询准备阶段：并行执行所有 LLM 调用（约束提取 + 改写 + HyDE）。
        结果可复用于多个知识库，避免每个知识库重复调用 LLM。
        """
        coarse_n = n_results * 2 if use_rerank else n_results

        # 所有 LLM 调用并行启动
        from app.services.rag.query_rewriter import (
            extract_constraints_llm, rewrite_query, hyde_rewrite,
        )

        coros = {}
        coros['constraints'] = extract_constraints_llm(query_text)
        if use_rewrite:
            coros['rewrite'] = rewrite_query(query_text, n_rewrites=3)
        if use_hyde:
            coros['hyde'] = hyde_rewrite(query_text)

        # 一次 asyncio.gather 并行执行所有 LLM 调用
        keys = list(coros.keys())
        results = await asyncio.gather(
            *coros.values(), return_exceptions=True,
        )
        result_map = dict(zip(keys, results))

        # 解析约束（只做软约束：提取结果用于 Constraint Boost 加权，不做 ChromaDB 硬过滤）
        constraints = None
        metadata_filter = None
        c_result = result_map.get('constraints')
        if c_result and not isinstance(c_result, Exception):
            constraints = c_result
            if constraints.has_constraints():
                logger.info(
                    f"🔎 [约束提取] year={constraints.year}, "
                    f"dept={constraints.department} (软约束，不做 ChromaDB 硬过滤)"
                )

        # 解析改写结果（如果约束提取成功且有 semantic_query，用它替换改写输入）
        queries = [query_text]
        rw_result = result_map.get('rewrite')
        if rw_result and not isinstance(rw_result, Exception) and rw_result:
            queries = rw_result

        # 解析 HyDE
        hyde_text = None
        h_result = result_map.get('hyde')
        if h_result and not isinstance(h_result, Exception) and h_result:
            hyde_text = h_result

        logger.info(
            f"🚀 [查询准备完成] queries={len(queries)}, "
            f"hyde={'✓' if hyde_text else '✗'}, "
            f"constraints={'✓' if constraints and constraints.has_constraints() else '✗'}"
        )

        return VectorRetriever.PreparedQuery(
            original_query=query_text,
            queries=queries,
            hyde_text=hyde_text,
            constraints=constraints,
            metadata_filter=metadata_filter,
            use_rerank=use_rerank,
            use_graph=use_graph,
            coarse_n=coarse_n,
        )

    # ---- 检索执行（纯 DB 操作 + Rerank，复用 PreparedQuery）----

    @staticmethod
    async def execute_prepared_query(
        vector_db_id: int,
        prepared: "VectorRetriever.PreparedQuery",
        n_results: int = 5,
        alpha: float = 0.7,
        folder_path: Optional[str] = None,
        parent_id: Optional[int] = None,
        skip_rerank: bool = False,
    ) -> List[RetrievalResult]:
        """
        检索执行阶段：使用已准备好的查询（改写结果、约束条件等），
        只做 DB 检索 + Rerank，不再调用 LLM。
        skip_rerank=True 时只做粗排，由调用方统一做合并 rerank。
        """
        from app.services.rag.monitor import RAGTimer, RAGQueryMetrics, get_rag_monitor
        timer = RAGTimer()

        retrieval_tasks = [
            VectorRetriever.hybrid_query(
                vector_db_id, q, prepared.coarse_n, alpha, folder_path, parent_id,
                metadata_filter=prepared.metadata_filter,
            )
            for q in prepared.queries
        ]
        if prepared.hyde_text:
            retrieval_tasks.append(
                VectorRetriever.query(
                    vector_db_id, prepared.hyde_text, prepared.coarse_n,
                    folder_path, parent_id,
                )
            )

        graph_task = None
        if prepared.use_graph:
            try:
                from app.services.rag.graph_rag import graph_augmented_retrieval, NEO4J_ENABLED
                if NEO4J_ENABLED:
                    graph_task = graph_augmented_retrieval(prepared.original_query, vector_db_id)
            except ImportError:
                pass

        if graph_task:
            retrieval_tasks.append(graph_task)

        timer.start("retrieval")
        multi_results = await asyncio.gather(*retrieval_tasks, return_exceptions=True)
        timer.stop()
        _retrieval_total = timer.get("retrieval")

        seen_chunks = set()
        all_results: List[RetrievalResult] = []
        graph_triples = []

        for result in multi_results:
            if isinstance(result, Exception):
                logger.warning(f"检索路径失败: {result}")
                continue
            if isinstance(result, list) and result and isinstance(result[0], dict):
                graph_triples = result
                continue
            if isinstance(result, list):
                for r in result:
                    if hasattr(r, 'chunk_id') and r.chunk_id not in seen_chunks:
                        all_results.append(r)
                        seen_chunks.add(r.chunk_id)

        # GraphRAG 三元组不再混入候选池（已提升到全局层级，作为上下文注入）
        if graph_triples:
            logger.info(f"📊 [GraphRAG] 单库查到 {len(graph_triples)} 条三元组（已由全局路径处理）")

        all_results.sort(key=lambda r: r.score, reverse=True)
        coarse_results = all_results[:prepared.coarse_n]

        pre_rerank_top1 = coarse_results[0].chunk_id if coarse_results else ""

        if not skip_rerank and prepared.use_rerank and len(coarse_results) > 1:
            try:
                from app.services.rag.reranker import rerank
                timer.start("rerank")
                final_results = await rerank(prepared.original_query, coarse_results, top_k=n_results)
                timer.stop()
            except Exception as e:
                logger.warning(f"Reranker 失败，降级为粗排: {e}")
                final_results = coarse_results[:n_results]
        else:
            final_results = coarse_results[:n_results]

        final_results = _mmr_diversify(final_results, n_results)

        if prepared.constraints and prepared.constraints.has_constraints():
            for r in final_results:
                r.metadata['_query_constraints'] = {
                    'year': prepared.constraints.year,
                    'department': prepared.constraints.department,
                    'category': prepared.constraints.category,
                    'constraint_hint': prepared.constraints.to_prompt_hint(),
                }

        post_rerank_top1 = final_results[0].chunk_id if final_results else ""
        top1_sim = final_results[0].similarity if final_results else 0
        avg_sim = sum(r.similarity for r in final_results) / len(final_results) if final_results else 0

        metrics = RAGQueryMetrics(
            query_id=prepared.original_query[:40],
            vector_search_ms=timer.get("retrieval"),
            bm25_search_ms=timer.get("retrieval"),
            rerank_ms=timer.get("rerank"),
            total_ms=timer.total,
            result_count=len(final_results),
            top1_similarity=top1_sim,
            avg_similarity=avg_sim,
            rerank_changed_top1=(pre_rerank_top1 != post_rerank_top1 and prepared.use_rerank),
            retrieval_method=final_results[0].retrieval_method if final_results else "none",
            low_confidence=(top1_sim < 0.4),
        )
        get_rag_monitor().record(metrics)

        return final_results

    # ---- 兼容接口：单知识库场景直接调用 ----

    @staticmethod
    async def enhanced_query(
        vector_db_id: int,
        query_text: str,
        n_results: int = 5,
        alpha: float = 0.7,
        use_rewrite: bool = True,
        use_rerank: bool = True,
        use_hyde: bool = False,
        use_graph: bool = True,
        folder_path: Optional[str] = None,
        parent_id: Optional[int] = None,
    ) -> List[RetrievalResult]:
        """兼容接口：prepare + execute 合并调用。"""
        prepared = await VectorRetriever.prepare_query(
            query_text, n_results, use_rewrite, use_rerank, use_hyde, use_graph,
        )
        return await VectorRetriever.execute_prepared_query(
            vector_db_id, prepared, n_results, alpha, folder_path, parent_id,
        )


# ------------------------------------------------------------------
# 缓存失效接口（文档变更时调用）
# ------------------------------------------------------------------

def invalidate_bm25_cache(vector_db_id: int) -> None:
    """使指定知识库的 BM25 索引缓存失效"""
    if vector_db_id in _BM25_CACHE:
        del _BM25_CACHE[vector_db_id]
        logger.info(f"BM25 缓存已失效: vector_db_id={vector_db_id}")
