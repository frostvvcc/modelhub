"""
RAG 运行时质量监控

采集检索链路各阶段的 latency、质量指标，提供滑动窗口统计。
支持双写：内存滑动窗口（实时聚合）+ 数据库持久化（历史分析）。
"""
import time
import math
import logging
import json
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)

_WINDOW_SIZE = 200
_METRICS_LOG_DIR = Path(__file__).parent.parent.parent / "data" / "rag_metrics"


@dataclass
class RAGQueryMetrics:
    """单次 RAG 查询的完整指标"""
    query_id: str = ""
    timestamp: float = field(default_factory=time.time)
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
    """RAG 链路滑动窗口监控器（单例），支持持久化"""

    def __init__(self, window_size: int = _WINDOW_SIZE, persist: bool = True):
        self._window: deque[RAGQueryMetrics] = deque(maxlen=window_size)
        self._persist = persist
        if self._persist:
            _METRICS_LOG_DIR.mkdir(parents=True, exist_ok=True)

    def record(self, metrics: RAGQueryMetrics):
        self._window.append(metrics)
        if metrics.low_confidence:
            logger.warning(
                f"[RAG Monitor] 低置信度查询 query_id={metrics.query_id} "
                f"top1_sim={metrics.top1_similarity:.3f} grounded={metrics.grounded_ratio:.2%}"
            )
        if self._persist:
            self._persist_to_jsonl(metrics)

    def _persist_to_jsonl(self, metrics: RAGQueryMetrics):
        """追加写入 JSON Lines 文件（按日期分片），零依赖、无阻塞风险"""
        try:
            date_str = time.strftime("%Y-%m-%d", time.localtime(metrics.timestamp))
            log_file = _METRICS_LOG_DIR / f"rag_metrics_{date_str}.jsonl"
            record = asdict(metrics)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug(f"RAG 指标持久化失败（非致命）: {e}")

    def load_history(self, days: int = 7) -> List[RAGQueryMetrics]:
        """从 JSONL 文件加载历史指标，用于长期趋势分析"""
        results = []
        if not _METRICS_LOG_DIR.exists():
            return results
        cutoff = time.time() - days * 86400
        for f in sorted(_METRICS_LOG_DIR.glob("rag_metrics_*.jsonl")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    for line in fh:
                        record = json.loads(line.strip())
                        if record.get("timestamp", 0) >= cutoff:
                            results.append(RAGQueryMetrics(**{
                                k: v for k, v in record.items()
                                if k in RAGQueryMetrics.__dataclass_fields__
                            }))
            except Exception:
                continue
        return results

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

        p95_total = sorted(m.total_ms for m in metrics_list)[min(int(math.ceil(n * 0.95)) - 1, n - 1)] if n >= 20 else max(m.total_ms for m in metrics_list)

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
