"""
Prometheus 指标导出 — RAG 链路运行时质量监控

在 RAGMonitor（内存滑窗 + JSONL 持久化）之上叠加标准 Prometheus 指标，
由应用的 GET /metrics 端点暴露，供 Prometheus / Grafana 抓取。

prometheus_client 缺失时全部降级为 no-op，不影响主链路。
"""
from typing import Optional, Tuple

from app.utils.logger_config import get_logger

logger = get_logger(__name__)

try:
    from prometheus_client import (
        Counter, Histogram, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client 未安装，/metrics 端点将返回 501")

_LATENCY_BUCKETS = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
_RATIO_BUCKETS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)

if PROMETHEUS_AVAILABLE:
    REGISTRY = CollectorRegistry()

    RAG_QUERIES_TOTAL = Counter(
        "rag_queries_total", "RAG 检索查询总数",
        ["retrieval_method"], registry=REGISTRY,
    )
    RAG_LOW_CONFIDENCE_TOTAL = Counter(
        "rag_low_confidence_queries_total", "低置信度（top1 相关度过低）查询总数",
        registry=REGISTRY,
    )
    RAG_RERANK_CHANGED_TOP1_TOTAL = Counter(
        "rag_rerank_changed_top1_total", "Rerank 改变了 top1 结果的查询总数",
        registry=REGISTRY,
    )
    RAG_CRAG_TRIGGERED_TOTAL = Counter(
        "rag_crag_triggered_total", "CRAG 纠错检索触发总数",
        registry=REGISTRY,
    )
    RAG_STAGE_LATENCY_MS = Histogram(
        "rag_stage_latency_milliseconds", "RAG 各阶段耗时（毫秒）",
        ["stage"], buckets=_LATENCY_BUCKETS, registry=REGISTRY,
    )
    RAG_TOP1_SIMILARITY = Histogram(
        "rag_top1_similarity", "top1 检索相关度分布",
        buckets=_RATIO_BUCKETS, registry=REGISTRY,
    )
    RAG_GROUNDED_RATIO = Histogram(
        "rag_grounded_ratio", "回答 grounding 比率分布",
        buckets=_RATIO_BUCKETS, registry=REGISTRY,
    )


def observe_query(metrics) -> None:
    """把一次 RAGQueryMetrics 记录同步到 Prometheus（best-effort）。"""
    if not PROMETHEUS_AVAILABLE:
        return
    try:
        RAG_QUERIES_TOTAL.labels(retrieval_method=metrics.retrieval_method or "none").inc()
        if metrics.low_confidence:
            RAG_LOW_CONFIDENCE_TOTAL.inc()
        if metrics.rerank_changed_top1:
            RAG_RERANK_CHANGED_TOP1_TOTAL.inc()
        for stage, value in (
            ("retrieval", metrics.vector_search_ms),
            ("rerank", metrics.rerank_ms),
            ("grounding", metrics.grounding_ms),
            ("total", metrics.total_ms),
        ):
            if value:
                RAG_STAGE_LATENCY_MS.labels(stage=stage).observe(value)
        RAG_TOP1_SIMILARITY.observe(max(0.0, min(1.0, metrics.top1_similarity)))
    except Exception as e:
        logger.debug(f"Prometheus 指标记录失败（非致命）: {e}")


def observe_grounded_ratio(ratio: float) -> None:
    if not PROMETHEUS_AVAILABLE:
        return
    try:
        RAG_GROUNDED_RATIO.observe(max(0.0, min(1.0, ratio)))
    except Exception:
        pass


def inc_crag_triggered() -> None:
    if not PROMETHEUS_AVAILABLE:
        return
    try:
        RAG_CRAG_TRIGGERED_TOTAL.inc()
    except Exception:
        pass


def render_latest() -> Optional[Tuple[bytes, str]]:
    """生成 Prometheus 文本格式输出；不可用时返回 None。"""
    if not PROMETHEUS_AVAILABLE:
        return None
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
