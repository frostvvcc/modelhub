"""
LangGraph 多 Agent 编排器 — 基于 CRAG (Corrective RAG) 的状态图编排

使用 LangGraph StateGraph 实现可视化、可检查点的多 Agent 工作流：
  retrieve → synthesize → verify → [corrective_retrieve → synthesize] → END

通过 asyncio.Queue 实现真流式：节点执行过程中实时推送 SSE 事件，
不等整个图跑完，用户体验与 ReAct Agent 一致。

参考:
  - Yan et al., "Corrective Retrieval Augmented Generation", 2024
  - LangGraph Documentation: https://langchain-ai.github.io/langgraph/
"""
import asyncio
import json
from typing import List, Dict, Any, Optional, TypedDict, Annotated

from langgraph.graph import StateGraph, END

from app.services.agent.engine import AgentEvent
from app.services.agent.trace import TraceContext
from app.config import settings
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


def _merge_lists(left: list, right: list) -> list:
    return left + right


class OrchestratorState(TypedDict):
    query: str
    conversation_messages: List[Dict[str, str]]
    system_prompt: str
    retrieval_sources: Annotated[List[Dict[str, Any]], _merge_lists]
    retrieval_context: str
    answer: str
    grounded_ratio: float
    grounding_detail: Dict[str, Any]
    crag_triggered: bool
    corrective_context: str
    iteration: int


class LangGraphOrchestrator:
    """
    基于 LangGraph 的 CRAG 编排器。
    Graph: retrieve → synthesize → verify → [corrective_retrieve → synthesize] → END
    """

    MAX_CRAG_ITERATIONS = 2

    def __init__(
        self,
        llm_client: Any,
        vector_db_ids: Optional[List[int]] = None,
        user_id: Optional[int] = None,
        session: Optional[Any] = None,
        model_config_id: Optional[int] = None,
    ):
        self.llm_client = llm_client
        self.vector_db_ids = vector_db_ids or []
        self.user_id = user_id
        self.session = session
        self.model_config_id = model_config_id
        self._event_queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self.trace = TraceContext()
        self._graph = self._build_graph()

    def _emit(self, event_type: str, data: Dict[str, Any]):
        self._event_queue.put_nowait(AgentEvent(type=event_type, data=data))

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(OrchestratorState)
        graph.add_node("retrieve", self._node_retrieve)
        graph.add_node("synthesize", self._node_synthesize)
        graph.add_node("verify", self._node_verify)
        graph.add_node("corrective_retrieve", self._node_corrective_retrieve)

        graph.set_entry_point("retrieve")
        graph.add_edge("retrieve", "synthesize")
        graph.add_edge("synthesize", "verify")
        graph.add_conditional_edges(
            "verify",
            self._route_after_verify,
            {"pass": END, "corrective": "corrective_retrieve"},
        )
        graph.add_edge("corrective_retrieve", "synthesize")
        return graph.compile()

    # ── Retrieve ──

    async def _node_retrieve(self, state: OrchestratorState) -> dict:
        from app.services.vector_service import AsyncVectorService

        query = state["query"]
        self._emit("state_change", {"state": "tool_calling", "label": "知识库检索中..."})
        self._emit("tool_call", {"tool": "knowledge_search", "args": {"query": query}, "call_id": "lg_retrieve"})

        retrieve_span = self.trace.create_span("retrieve", span_type="tool_call", input_data={"query": query})

        try:
            rag_result = await AsyncVectorService.query_vector_by_model(
                self.session,
                self.model_config_id,
                query,
                user_id=self.user_id,
                extra_vector_db_ids=self.vector_db_ids,
            )
        except Exception as e:
            logger.error(f"[LangGraph:retrieve] 检索失败: {e}")
            retrieve_span.finish(error=str(e))
            self._emit("tool_result", {
                "tool": "knowledge_search", "call_id": "lg_retrieve",
                "result": {"error": str(e), "found": False}, "latency_ms": retrieve_span.latency_ms,
            })
            return {"retrieval_sources": [], "retrieval_context": ""}

        sources = rag_result.get("sources", [])
        formatted = []
        per_budget = 3000 // max(len(sources), 1)
        for i, s in enumerate(sources):
            content = (s.get("content") or "").strip()
            if len(content) > per_budget:
                content = content[:per_budget] + "..."
            formatted.append({
                "index": i + 1,
                "content": content,
                "source": s.get("source", "未知"),
                "similarity": round(s.get("similarity", 0), 4),
                "vector_score": round(s.get("vector_score", 0), 4),
                "bm25_score": round(s.get("bm25_score", 0), 4),
                "retrieval_method": s.get("retrieval_method", "vector"),
            })

        context = "\n\n".join(
            f"[来源{s['index']}]（{s['source']}）\n{s['content']}" for s in formatted
        )

        tool_result_data = {
            "found": len(formatted) > 0,
            "count": len(formatted),
            "total_found": rag_result.get("total_found", len(formatted)),
            "sources": formatted,
            "avg_similarity": round(rag_result.get("avg_similarity", 0), 4),
            "vector_db_ids": rag_result.get("vector_db_ids", []),
            "queried_vector_db_ids": rag_result.get("queried_vector_db_ids", []),
            "has_result_db_ids": rag_result.get("has_result_db_ids", []),
        }

        retrieve_span.finish(output={"source_count": len(formatted)})
        self._emit("tool_result", {
            "tool": "knowledge_search", "call_id": "lg_retrieve",
            "result": tool_result_data, "latency_ms": retrieve_span.latency_ms,
        })

        graph_context = rag_result.get("graph_context", "")
        if graph_context:
            context += f"\n\n【知识图谱补充】\n{graph_context}"

        return {"retrieval_sources": formatted, "retrieval_context": context}

    # ── Synthesize ──

    async def _node_synthesize(self, state: OrchestratorState) -> dict:
        self._emit("state_change", {"state": "responding", "label": "生成回答中..."})

        context_parts = []
        if state.get("retrieval_context"):
            context_parts.append(state["retrieval_context"])
        if state.get("corrective_context"):
            context_parts.append(f"【CRAG 补充检索】\n{state['corrective_context']}")
        combined = "\n\n".join(context_parts)

        messages = []
        sys_prompt = state.get("system_prompt", "")
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})

        messages.append({"role": "system", "content": (
            "基于以下参考资料回答用户问题。\n"
            "【引用规则 — 必须遵守】\n"
            "1. 回答中每个来自参考资料的事实都必须标注来源编号，如 [来源1]。\n"
            "2. 来源编号必须与参考资料中的 [来源N] 一一对应，不可编造。\n"
            "3. 如果资料不足以回答，请明确说明「当前知识库依据不足」。\n\n"
            f"参考资料：\n{combined[:6000]}"
        )})

        if state.get("conversation_messages"):
            messages.extend(state["conversation_messages"][-6:])
        messages.append({"role": "user", "content": state["query"]})

        synth_span = self.trace.create_span("synthesize", span_type="llm_stream", input_data={"context_len": len(combined)})

        try:
            client = self.llm_client._get_client()
            stream = await client.chat.completions.create(
                model=self.llm_client.model,
                messages=messages,
                temperature=self.llm_client.temperature,
                max_tokens=4096,
                stream=True,
            )
            answer = ""
            token_count = 0
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    answer += delta.content
                    token_count += 1
                    self._emit("token", {"content": delta.content})

            synth_span.completion_tokens = token_count
            synth_span.finish(output={"content_length": len(answer)})
            return {"answer": answer}

        except Exception as e:
            logger.error(f"[LangGraph:synthesize] 失败: {e}")
            synth_span.finish(error=str(e))
            self._emit("error", {"message": f"回答生成失败: {e}"})
            return {"answer": "抱歉，生成回答时出现错误。"}

    # ── Verify (CRAG) ──

    async def _node_verify(self, state: OrchestratorState) -> dict:
        answer = state.get("answer", "")
        sources = state.get("retrieval_sources", [])

        if not answer or not sources:
            return {"grounded_ratio": 1.0, "grounding_detail": {}, "crag_triggered": False}

        self._emit("state_change", {"state": "reflecting", "label": "验证回答质量..."})
        verify_span = self.trace.create_span("verify", span_type="grounding", input_data={"answer_len": len(answer)})

        try:
            from app.services.rag.grounding import verify_grounding
            grounding_result = await verify_grounding(answer, sources)

            ratio = grounding_result.get("grounded_ratio", 1.0)
            threshold = getattr(settings, "grounding_threshold", 0.5)
            iteration = state.get("iteration", 0)
            needs_correction = ratio < threshold and iteration < self.MAX_CRAG_ITERATIONS

            if needs_correction:
                logger.info(f"[CRAG] grounded_ratio={ratio:.2f} < {threshold}, 触发补充检索 (iteration={iteration})")

            verify_span.finish(output={"ratio": ratio, "crag": needs_correction})
            self._emit("state_change", {
                "state": "reflecting",
                "label": f"Grounding 验证: {ratio:.0%}" + (" → 触发 CRAG 补充检索" if needs_correction else " → 通过"),
            })

            return {
                "grounded_ratio": ratio,
                "grounding_detail": grounding_result,
                "crag_triggered": needs_correction,
                "iteration": iteration + 1,
            }
        except Exception as e:
            logger.warning(f"[LangGraph:verify] Grounding 失败: {e}")
            verify_span.finish(error=str(e))
            return {"grounded_ratio": 0.0, "grounding_detail": {"error": str(e)}, "crag_triggered": False}

    # ── Corrective Retrieve ──

    async def _node_corrective_retrieve(self, state: OrchestratorState) -> dict:
        self._emit("state_change", {"state": "tool_calling", "label": "CRAG 补充检索中..."})

        grounding_detail = state.get("grounding_detail", {})
        unsupported = grounding_detail.get("unsupported_claims", [])
        if not unsupported:
            return {"corrective_context": ""}

        crag_span = self.trace.create_span("corrective_retrieve", span_type="tool_call")

        try:
            from app.services.rag.graph_rag import (
                NEO4J_ENABLED, extract_query_entities, query_subgraph, format_triples_for_context,
            )
            if not NEO4J_ENABLED:
                crag_span.finish(output={"skipped": "neo4j_disabled"})
                return {"corrective_context": ""}

            claim_texts = [c.get("text", "") for c in unsupported[:3]]
            entities = await extract_query_entities(" ".join(claim_texts))
            if not entities:
                crag_span.finish(output={"entities": 0})
                return {"corrective_context": ""}

            all_triples = []
            for vdb_id in self.vector_db_ids[:2]:
                triples = await asyncio.to_thread(query_subgraph, entities, vdb_id)
                all_triples.extend(triples)

            context = format_triples_for_context(all_triples)
            crag_span.finish(output={"triples": len(all_triples)})

            self._emit("state_change", {
                "state": "tool_calling",
                "label": f"CRAG 补充检索完成: {len(all_triples)} 条三元组",
            })

            return {"corrective_context": context}
        except Exception as e:
            logger.warning(f"[LangGraph:corrective] 补充检索失败: {e}")
            crag_span.finish(error=str(e))
            return {"corrective_context": ""}

    # ── Routing ──

    def _route_after_verify(self, state: OrchestratorState) -> str:
        return "corrective" if state.get("crag_triggered", False) else "pass"

    # ── Public API ──

    async def run(
        self,
        query: str,
        conversation_messages: Optional[List[Dict[str, str]]] = None,
        system_prompt: str = "",
    ):
        self._emit("state_change", {"state": "planning", "label": "分析问题中..."})

        initial_state: OrchestratorState = {
            "query": query,
            "conversation_messages": conversation_messages or [],
            "system_prompt": system_prompt,
            "retrieval_sources": [],
            "retrieval_context": "",
            "answer": "",
            "grounded_ratio": 0.0,
            "grounding_detail": {},
            "crag_triggered": False,
            "corrective_context": "",
            "iteration": 0,
        }

        graph_task = asyncio.create_task(self._run_graph(initial_state))

        while True:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=0.05)
                yield event
            except asyncio.TimeoutError:
                if graph_task.done():
                    break

        while not self._event_queue.empty():
            yield self._event_queue.get_nowait()

        exc = graph_task.exception() if graph_task.done() and not graph_task.cancelled() else None
        if exc:
            raise exc
        final_state = graph_task.result()

        self.trace.finish()
        sources = final_state.get("retrieval_sources", [])

        yield AgentEvent(type="done", data={
            "content": final_state.get("answer", ""),
            "sources": sources,
            "grounded_ratio": final_state.get("grounded_ratio", 0.0),
            "crag_triggered": final_state.get("crag_triggered", False),
        })
        yield AgentEvent(type="trace", data=self.trace.to_dict())

    async def _run_graph(self, initial_state: OrchestratorState) -> dict:
        try:
            return await self._graph.ainvoke(initial_state)
        except Exception as e:
            logger.error(f"[LangGraph] 图执行失败: {e}", exc_info=True)
            self._emit("error", {"message": f"编排执行失败: {e}"})
            return {**initial_state, "answer": "抱歉，处理过程中出现错误。"}

    def get_graph_mermaid(self) -> str:
        try:
            return self._graph.get_graph().draw_mermaid()
        except Exception:
            return ""
