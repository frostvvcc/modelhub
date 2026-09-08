"""Prometheus 指标导出单元测试"""
import pytest

from app.services.rag.monitor import RAGQueryMetrics
from app.services.rag import prometheus_metrics as pm


pytestmark = pytest.mark.skipif(
    not pm.PROMETHEUS_AVAILABLE, reason="prometheus_client 未安装"
)


def _render_text() -> str:
    payload, content_type = pm.render_latest()
    assert "text/plain" in content_type
    return payload.decode("utf-8")


class TestPrometheusMetrics:
    def test_observe_query_updates_counters(self):
        metrics = RAGQueryMetrics(
            query_id="q1", vector_search_ms=120, rerank_ms=45, total_ms=200,
            result_count=3, top1_similarity=0.82, retrieval_method="hybrid",
            rerank_changed_top1=True, low_confidence=False,
        )
        pm.observe_query(metrics)
        text = _render_text()
        assert 'rag_queries_total{retrieval_method="hybrid"}' in text
        assert "rag_rerank_changed_top1_total" in text
        assert "rag_stage_latency_milliseconds_bucket" in text

    def test_low_confidence_counted(self):
        before = _render_text()
        pm.observe_query(RAGQueryMetrics(query_id="q2", top1_similarity=0.1, low_confidence=True))
        after = _render_text()

        def _value(text):
            for line in text.splitlines():
                if line.startswith("rag_low_confidence_queries_total "):
                    return float(line.split()[-1])
            return 0.0

        assert _value(after) == _value(before) + 1

    def test_crag_trigger_and_grounded_ratio(self):
        pm.inc_crag_triggered()
        pm.observe_grounded_ratio(0.75)
        text = _render_text()
        assert "rag_crag_triggered_total" in text
        assert "rag_grounded_ratio_bucket" in text

    def test_monitor_record_feeds_prometheus(self):
        from app.services.rag.monitor import RAGMonitor
        monitor = RAGMonitor(persist=False)
        monitor.record(RAGQueryMetrics(query_id="q3", retrieval_method="vector", total_ms=50))
        text = _render_text()
        assert 'rag_queries_total{retrieval_method="vector"}' in text
