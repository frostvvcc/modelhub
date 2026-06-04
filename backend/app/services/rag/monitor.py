"""
RAG 运行时质量监控

采集检索链路各阶段的 latency、质量指标，提供滑动窗口统计。
用于线上监控 RAG 质量退化和性能瓶颈。
"""
import time
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

_WINDOW_SIZE = 200


@dataclass
class RAGQueryMetrics:
    """单次 RAG 查询的完整指标"""
    query_id: str = ""
    vector_search_ms: float = 0
    bm25_search_ms: float = 0
    rerank_ms: float = 0
    grounding_ms: float = 0
    total_ms: float = 0
    result_count: int = 0
    top1_similarity: float = 0
    avg_similarity: float = 0
    rerank_changed_top1: bool = False
    grounded_ratio: float = 1.0
    retrieval_method: str = ""
    low_confidence: bool = False


class RAGMonitor:
    """RAG 链路滑动窗口监控器（单例）"""

    def __init__(self, window_size: int = _WINDOW_SIZE):
        self._window: deque[RAGQueryMetrics] = deque(maxlen=window_size)

    def record(self, metrics: RAGQueryMetrics):
        self._window.append(metrics)
        if metrics.low_confidence:
            logger.warning(
                f"[RAG Monitor] 低置信度查询 query_id={metrics.query_id} "
                f"top1_sim={metrics.top1_similarity:.3f} grounded={metrics.grounded_ratio:.2%}"
            )

    def get_stats(self) -> Dict[str, Any]:
        if not self._window:
            return {"status": "no_data", "count": 0}

        n = len(self._window)
        metrics_list = list(self._window)

        avg_total = sum(m.total_ms for m in metrics_list) / n
        avg_vector = sum(m.vector_search_ms for m in metrics_list) / n
        avg_bm25 = sum(m.bm25_search_ms for m in metrics_list) / n
        avg_rerank = sum(m.rerank_ms for m in metrics_list) / n
        avg_grounding = sum(m.grounding_ms for m in metrics_list) / n
        avg_similarity = sum(m.top1_similarity for m in metrics_list) / n
        avg_grounded = sum(m.grounded_ratio for m in metrics_list) / n

        rerank_change_rate = sum(1 for m in metrics_list if m.rerank_changed_top1) / n
        low_confidence_rate = sum(1 for m in metrics_list if m.low_confidence) / n

        p95_total = sorted(m.total_ms for m in metrics_list)[int(n * 0.95)] if n >= 20 else max(m.total_ms for m in metrics_list)

        return {
            "count": n,
            "latency": {
                "avg_total_ms": round(avg_total, 1),
                "p95_total_ms": round(p95_total, 1),
                "avg_vector_ms": round(avg_vector, 1),
                "avg_bm25_ms": round(avg_bm25, 1),
                "avg_rerank_ms": round(avg_rerank, 1),
                "avg_grounding_ms": round(avg_grounding, 1),
            },
            "quality": {
                "avg_top1_similarity": round(avg_similarity, 4),
                "avg_grounded_ratio": round(avg_grounded, 4),
                "rerank_change_rate": round(rerank_change_rate, 4),
                "low_confidence_rate": round(low_confidence_rate, 4),
            },
        }


_monitor: Optional[RAGMonitor] = None


def get_rag_monitor() -> RAGMonitor:
    global _monitor
    if _monitor is None:
        _monitor = RAGMonitor()
    return _monitor


class RAGTimer:
    """上下文管理器，测量各阶段耗时"""

    def __init__(self):
        self.stages: Dict[str, float] = {}
        self._current_stage: Optional[str] = None
        self._start: float = 0

    def start(self, stage: str):
        self._current_stage = stage
        self._start = time.perf_counter()

    def stop(self):
        if self._current_stage:
            elapsed = (time.perf_counter() - self._start) * 1000
            self.stages[self._current_stage] = elapsed
            self._current_stage = None

    def get(self, stage: str) -> float:
        return self.stages.get(stage, 0)

    @property
    def total(self) -> float:
        return sum(self.stages.values())
