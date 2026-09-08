"""
LangGraphOrchestrator (CRAG) 单元测试

重点验证恢复 CRAG 纠错循环后的关键不变量：
1. 检索质量差 → 触发查询改写 + 补充检索（有上限）
2. 无论是否纠错，synthesize 只执行一次 → 不存在回答重复生成
3. 补充检索的来源与首轮合并且编号连续、内容去重
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import settings
from app.services.agent.graph_orchestrator import LangGraphOrchestrator


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

class FakeStream:
    """模拟 OpenAI 流式响应"""

    def __init__(self, tokens):
        self._tokens = tokens

    def __aiter__(self):
        self._iter = iter(self._tokens)
        return self

    async def __anext__(self):
        try:
            token = next(self._iter)
        except StopIteration:
            raise StopAsyncIteration
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = token
        return chunk


def make_llm_client(tokens=("你", "好")):
    """构造带流式生成能力的假 LLM 客户端，并记录生成调用次数"""
    llm = MagicMock()
    llm.model = "fake-model"
    llm.temperature = 0.3

    inner = MagicMock()
    calls = []

    async def fake_create(**kwargs):
        calls.append(kwargs)
        if kwargs.get("stream"):
            return FakeStream(list(tokens))
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = "[true, true]"
        return resp

    inner.chat.completions.create = fake_create
    llm._get_client.return_value = inner
    return llm, calls


def rag_result(sources):
    return {"sources": sources, "total_found": len(sources), "avg_similarity": 0.5}


def source(content, similarity):
    return {"content": content, "source": "doc.pdf", "similarity": similarity,
            "vector_score": similarity, "bm25_score": 0.1, "retrieval_method": "hybrid"}


async def collect_events(orchestrator, query="毕设查重怎么弄"):
    events = []
    async for ev in orchestrator.run(query):
        events.append(ev)
    return events


# ------------------------------------------------------------------
# tests
# ------------------------------------------------------------------

class TestCragGraph:
    @pytest.mark.asyncio
    async def test_good_retrieval_skips_correction(self, monkeypatch):
        llm, calls = make_llm_client()
        orch = LangGraphOrchestrator(llm_client=llm, session=MagicMock(), model_config_id=1)

        retrieve_mock = AsyncMock(return_value=rag_result([source("高相关内容", 0.9)]))
        with patch("app.services.vector_service.AsyncVectorService.query_vector_by_model", retrieve_mock):
            events = await collect_events(orch)

        assert retrieve_mock.await_count == 1
        stream_calls = [c for c in calls if c.get("stream")]
        assert len(stream_calls) == 1

        done = next(e for e in events if e.type == "done")
        assert done.data["crag_triggered"] is False
        assert done.data["content"] == "你好"

    @pytest.mark.asyncio
    async def test_low_score_triggers_single_correction_and_single_synthesis(self, monkeypatch):
        monkeypatch.setattr(settings, "crag_max_retries", 1)
        monkeypatch.setattr(settings, "crag_score_threshold", 0.35)
        llm, calls = make_llm_client()
        orch = LangGraphOrchestrator(llm_client=llm, session=MagicMock(), model_config_id=1)

        retrieve_mock = AsyncMock(side_effect=[
            rag_result([source("弱相关内容", 0.1)]),
            rag_result([source("改写后命中的内容", 0.8)]),
        ])
        rewrite_mock = AsyncMock(return_value=["毕设查重怎么弄", "毕业设计论文查重检测流程"])

        with patch("app.services.vector_service.AsyncVectorService.query_vector_by_model", retrieve_mock), \
             patch("app.services.rag.query_rewriter.rewrite_query", rewrite_mock):
            events = await collect_events(orch)

        assert retrieve_mock.await_count == 2
        # 第二次检索使用了改写后的查询
        assert retrieve_mock.await_args_list[1].args[2] == "毕业设计论文查重检测流程"

        # 核心不变量：无论纠错与否，生成只发生一次
        stream_calls = [c for c in calls if c.get("stream")]
        assert len(stream_calls) == 1

        done = next(e for e in events if e.type == "done")
        assert done.data["crag_triggered"] is True
        assert done.data["crag_iterations"] == 1

        # 来源合并且编号连续
        indexes = [s["index"] for s in done.data["sources"]]
        assert indexes == [1, 2]

    @pytest.mark.asyncio
    async def test_correction_bounded_when_still_insufficient(self, monkeypatch):
        monkeypatch.setattr(settings, "crag_max_retries", 1)
        llm, calls = make_llm_client()
        orch = LangGraphOrchestrator(llm_client=llm, session=MagicMock(), model_config_id=1)

        retrieve_mock = AsyncMock(return_value=rag_result([]))
        rewrite_mock = AsyncMock(return_value=["原查询", "改写查询"])

        with patch("app.services.vector_service.AsyncVectorService.query_vector_by_model", retrieve_mock), \
             patch("app.services.rag.query_rewriter.rewrite_query", rewrite_mock):
            events = await collect_events(orch)

        # 首轮 + 1 次纠错重试后必须停止，仍然生成兜底回答
        assert retrieve_mock.await_count == 2
        stream_calls = [c for c in calls if c.get("stream")]
        assert len(stream_calls) == 1
        done = next(e for e in events if e.type == "done")
        assert done.data["content"] == "你好"

    @pytest.mark.asyncio
    async def test_duplicate_chunks_deduped_on_corrective_round(self, monkeypatch):
        monkeypatch.setattr(settings, "crag_max_retries", 1)
        llm, _ = make_llm_client()
        orch = LangGraphOrchestrator(llm_client=llm, session=MagicMock(), model_config_id=1)

        dup = source("重复的chunk", 0.1)
        retrieve_mock = AsyncMock(side_effect=[
            rag_result([dup]),
            rag_result([dup, source("新增内容", 0.6)]),
        ])
        rewrite_mock = AsyncMock(return_value=["原查询", "改写查询"])

        with patch("app.services.vector_service.AsyncVectorService.query_vector_by_model", retrieve_mock), \
             patch("app.services.rag.query_rewriter.rewrite_query", rewrite_mock):
            events = await collect_events(orch)

        done = next(e for e in events if e.type == "done")
        contents = [s["content"] for s in done.data["sources"]]
        assert contents == ["重复的chunk", "新增内容"]
        assert [s["index"] for s in done.data["sources"]] == [1, 2]

    @pytest.mark.asyncio
    async def test_crag_disabled_bypasses_grading(self, monkeypatch):
        monkeypatch.setattr(settings, "crag_enabled", False)
        llm, calls = make_llm_client()
        orch = LangGraphOrchestrator(llm_client=llm, session=MagicMock(), model_config_id=1)

        retrieve_mock = AsyncMock(return_value=rag_result([]))
        with patch("app.services.vector_service.AsyncVectorService.query_vector_by_model", retrieve_mock):
            events = await collect_events(orch)

        assert retrieve_mock.await_count == 1
        done = next(e for e in events if e.type == "done")
        assert done.data["crag_triggered"] is False


class TestHeuristicGrade:
    def test_empty_sources_insufficient(self):
        ok, reason = LangGraphOrchestrator._heuristic_grade([])
        assert ok is False

    def test_low_top_score_insufficient(self, monkeypatch):
        monkeypatch.setattr(settings, "crag_score_threshold", 0.35)
        ok, _ = LangGraphOrchestrator._heuristic_grade([source("弱", 0.2)])
        assert ok is False

    def test_high_top_score_sufficient(self, monkeypatch):
        monkeypatch.setattr(settings, "crag_score_threshold", 0.35)
        ok, _ = LangGraphOrchestrator._heuristic_grade([source("弱", 0.2), source("强", 0.7)])
        assert ok is True
