"""
rag/retrieval 检索模块单元测试
主要测试 BM25 分词、RRF 融合、缓存失效
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.rag.retrieval import (
    VectorRetriever,
    RetrievalResult,
    invalidate_bm25_cache,
    _BM25_CACHE,
)


def make_result(chunk_id, content, score, vector_score=0.0, bm25_score=0.0, similarity=None, method="vector"):
    if similarity is None:
        similarity = vector_score if vector_score > 0 else bm25_score
    return RetrievalResult(
        chunk_id=chunk_id,
        content=content,
        score=score,
        vector_score=vector_score,
        bm25_score=bm25_score,
        similarity=similarity,
        retrieval_method=method,
    )


class TestRrfMerge:
    def test_merge_prefers_high_rank_in_both(self):
        v_results = [
            make_result("a", "内容A", 0.9, vector_score=0.9),
            make_result("b", "内容B", 0.8, vector_score=0.8),
            make_result("c", "内容C", 0.7, vector_score=0.7),
        ]
        b_results = [
            make_result("a", "内容A", 0.8, bm25_score=0.8),
            make_result("d", "内容D", 0.7, bm25_score=0.7),
        ]
        merged = VectorRetriever._rrf_merge(v_results, b_results, alpha=0.7, n_results=5)
        # "a" 在两路都排第一，应该排在最前面
        assert merged[0].chunk_id == "a"

    def test_merge_returns_at_most_n_results(self):
        v = [make_result(f"v{i}", f"内容{i}", 1.0 - i * 0.1) for i in range(10)]
        b = [make_result(f"b{i}", f"内容{i}", 1.0 - i * 0.1) for i in range(10)]
        merged = VectorRetriever._rrf_merge(v, b, alpha=0.5, n_results=5)
        assert len(merged) <= 5

    def test_merge_method_is_hybrid(self):
        v = [make_result("x", "X", 0.9, vector_score=0.9)]
        b = [make_result("x", "X", 0.8, bm25_score=0.8)]
        merged = VectorRetriever._rrf_merge(v, b, alpha=0.5, n_results=5)
        assert merged[0].retrieval_method == "hybrid"

    def test_merge_deduplicates(self):
        """同一 chunk_id 不应重复出现"""
        v = [make_result("same", "内容", 0.9)]
        b = [make_result("same", "内容", 0.8)]
        merged = VectorRetriever._rrf_merge(v, b, alpha=0.5, n_results=10)
        ids = [r.chunk_id for r in merged]
        assert len(ids) == len(set(ids))

    def test_empty_bm25_results(self):
        """BM25 无结果时，向量结果仍然返回"""
        v = [make_result("a", "A", 0.9)]
        merged = VectorRetriever._rrf_merge(v, [], alpha=1.0, n_results=5)
        assert len(merged) == 1
        assert merged[0].chunk_id == "a"


class TestTokenize:
    def test_basic_tokenize(self):
        tokens = VectorRetriever._tokenize("机器学习算法")
        assert len(tokens) > 0
        assert isinstance(tokens[0], str)

    def test_tokenize_english(self):
        tokens = VectorRetriever._tokenize("machine learning")
        assert len(tokens) >= 2

    def test_empty_string(self):
        tokens = VectorRetriever._tokenize("")
        assert isinstance(tokens, list)


class TestBm25Cache:
    def test_invalidate_removes_cache(self):
        # 手动塞一个假缓存
        _BM25_CACHE[9999] = {"bm25": None, "chunk_ids": [], "contents": [], "metas": []}
        assert 9999 in _BM25_CACHE
        invalidate_bm25_cache(9999)
        assert 9999 not in _BM25_CACHE

    def test_invalidate_nonexistent_key_no_error(self):
        # 不存在的 key 也不应报错
        invalidate_bm25_cache(99999999)


class TestRetrievalResult:
    def test_default_values(self):
        r = RetrievalResult(chunk_id="c1", content="内容", score=0.5)
        assert r.vector_score == 0.0
        assert r.bm25_score == 0.0
        assert r.similarity == 0.0
        assert r.retrieval_method == "vector"
        assert r.metadata == {}


class TestRrfSimilarity:
    def test_hybrid_similarity_combines_both_scores(self):
        """RRF 融合后 similarity 应该是 alpha*vector + (1-alpha)*bm25"""
        v = [make_result("a", "A", 0.9, vector_score=0.8)]
        b = [make_result("a", "A", 0.7, bm25_score=0.9)]
        merged = VectorRetriever._rrf_merge(v, b, alpha=0.7, n_results=5)
        expected_sim = 0.7 * 0.8 + 0.3 * 0.9
        assert abs(merged[0].similarity - expected_sim) < 0.001

    def test_bm25_only_result_has_nonzero_similarity(self):
        """仅 BM25 命中的结果 similarity 不应该为 0"""
        v = [make_result("a", "A", 0.9, vector_score=0.9)]
        b = [make_result("b", "B", 0.8, bm25_score=0.8)]
        merged = VectorRetriever._rrf_merge(v, b, alpha=0.7, n_results=5)
        b_result = next(r for r in merged if r.chunk_id == "b")
        assert b_result.similarity > 0.0
        assert abs(b_result.similarity - 0.3 * 0.8) < 0.001

    def test_vector_only_result_has_nonzero_similarity(self):
        """仅向量命中的结果 similarity 也不应该为 0"""
        v = [make_result("a", "A", 0.9, vector_score=0.85)]
        b = [make_result("b", "B", 0.8, bm25_score=0.7)]
        merged = VectorRetriever._rrf_merge(v, b, alpha=0.7, n_results=5)
        a_result = next(r for r in merged if r.chunk_id == "a")
        assert abs(a_result.similarity - 0.7 * 0.85) < 0.001


class TestNdcgMetric:
    def test_perfect_ranking(self):
        from eval.metrics import ndcg_at_k, QueryResult
        results = [QueryResult(query_id=1, retrieved_doc_ids=["a", "b"], relevant_doc_ids={"a", "b"})]
        assert ndcg_at_k(results, 5) == 1.0

    def test_empty_results(self):
        from eval.metrics import ndcg_at_k, QueryResult
        results = [QueryResult(query_id=1, retrieved_doc_ids=[], relevant_doc_ids={"a"})]
        assert ndcg_at_k(results, 5) == 0.0

    def test_partial_ranking(self):
        from eval.metrics import ndcg_at_k, QueryResult
        results = [QueryResult(query_id=1, retrieved_doc_ids=["x", "a"], relevant_doc_ids={"a"})]
        ndcg = ndcg_at_k(results, 5)
        assert 0 < ndcg < 1.0

    def test_no_relevant_docs(self):
        from eval.metrics import ndcg_at_k, QueryResult
        results = [QueryResult(query_id=1, retrieved_doc_ids=["a"], relevant_doc_ids=set())]
        assert ndcg_at_k(results, 5) == 0.0


class TestRagMonitor:
    def test_record_and_stats(self):
        from app.services.rag.monitor import RAGMonitor, RAGQueryMetrics
        monitor = RAGMonitor(window_size=10)
        for i in range(5):
            monitor.record(RAGQueryMetrics(
                query_id=f"q{i}", total_ms=100 + i * 10,
                top1_similarity=0.8, grounded_ratio=0.9,
            ))
        stats = monitor.get_stats()
        assert stats["count"] == 5
        assert stats["latency"]["avg_total_ms"] > 0
        assert stats["quality"]["avg_top1_similarity"] == 0.8

    def test_empty_stats(self):
        from app.services.rag.monitor import RAGMonitor
        monitor = RAGMonitor()
        assert monitor.get_stats()["status"] == "no_data"

    def test_low_confidence_flag(self):
        from app.services.rag.monitor import RAGMonitor, RAGQueryMetrics
        monitor = RAGMonitor(window_size=10)
        monitor.record(RAGQueryMetrics(
            query_id="low", top1_similarity=0.2, low_confidence=True,
        ))
        stats = monitor.get_stats()
        assert stats["quality"]["low_confidence_rate"] == 1.0


class TestBootstrapCI:
    def test_basic_ci(self):
        from eval.ablation import _bootstrap_ci
        values = [0.8, 0.85, 0.9, 0.75, 0.88, 0.92, 0.7, 0.95]
        ci = _bootstrap_ci(values)
        assert ci["ci_lower"] <= ci["mean"] <= ci["ci_upper"]
        assert ci["n"] == 8

    def test_small_sample(self):
        from eval.ablation import _bootstrap_ci
        ci = _bootstrap_ci([0.9, 0.8])
        assert ci["mean"] == 0.85

    def test_single_value(self):
        from eval.ablation import _bootstrap_ci
        ci = _bootstrap_ci([0.9])
        assert ci["mean"] == ci["ci_lower"] == ci["ci_upper"]


class TestE2eJsonExtract:
    def test_extract_json_from_code_block(self):
        from eval.e2e_eval import _extract_json
        text = '```json\n{"faithfulness": 4, "completeness": 5, "citation_quality": 3, "no_hallucination": 5, "reasoning": "ok"}\n```'
        result = _extract_json(text)
        assert result["faithfulness"] == 4
        assert result["no_hallucination"] == 5

    def test_extract_json_bare(self):
        from eval.e2e_eval import _extract_json
        text = '{"faithfulness": 3, "completeness": 4, "citation_quality": 2, "no_hallucination": 4, "reasoning": "test"}'
        result = _extract_json(text)
        assert result["completeness"] == 4

    def test_extract_regex_fallback(self):
        from eval.e2e_eval import _extract_json
        text = 'faithfulness: 4, completeness: 3, citation_quality: 2, no_hallucination: 5'
        result = _extract_json(text)
        assert result["faithfulness"] == 4
        assert result["no_hallucination"] == 5

    def test_invalid_raises(self):
        from eval.e2e_eval import _extract_json
        import pytest
        with pytest.raises(ValueError):
            _extract_json("这是一段完全无关的文字")
