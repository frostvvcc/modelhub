"""
LangGraph 多 Agent 编排器 — 基于 CRAG (Corrective RAG) 的状态图编排

使用 LangGraph StateGraph 实现可视化、可检查点的多 Agent 工作流：
  retrieve → grade → [transform_query → retrieve → grade]* → synthesize → END

与早期实现（synthesize 后 verify、失败再重新生成）的关键区别：
文档质量评估发生在**生成之前**。纠错只影响检索阶段，synthesize
仅在最后执行一次并全程流式输出——不存在回答重复生成，也不需要
content_reset。生成后的 grounding 校验仍在 stream_chat_service 中
后置执行，只用于前端展示标签，不触发重新生成。

评估信号优先使用检索管线自身的确定性分数（Cross-Encoder / 混合
检索相似度），可选叠加 temperature=0 的 LLM 文档相关性打分
（RAG_CRAG_LLM_GRADER），避免了旧版 claim-level NLI 验证结果随机
（同输入 33%→0%→100%）的问题。

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
    search_query: str
    conversation_messages: List[Dict[str, str]]
    system_prompt: str
    retrieval_sources: Annotated[List[Dict[str, Any]], _merge_lists]
    retrieval_context: str
    answer: str
    grounded_ratio: float
    grounding_detail: Dict[str, Any]
    sufficient: bool
    crag_triggered: bool
    iteration: int


class LangGraphOrchestrator:
    """
    基于 LangGraph 的 CRAG 编排器。
    Graph: retrieve → grade → [transform_query → retrieve → grade]* → synthesize → END
    """

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
        graph.add_node("grade", self._node_grade_documents)
        graph.add_node("transform_query", self._node_transform_query)
        graph.add_node("synthesize", self._node_synthesize)

        graph.set_entry_point("retrieve")
        graph.add_edge("retrieve", "grade")
        graph.add_conditional_edges(
            "grade",
            self._route_after_grade,
            {"synthesize": "synthesize", "transform": "transform_query"},
        )
        graph.add_edge("transform_query", "retrieve")
        graph.add_edge("synthesize", END)
        return graph.compile()

    # ── Retrieve ──

    async def _node_retrieve(self, state: OrchestratorState) -> dict:
        from app.services.vector_service import AsyncVectorService

        query = state.get("search_query") or state["query"]
        is_corrective = state.get("iteration", 0) > 0
        existing_sources = state.get("retrieval_sources", [])
        index_offset = len(existing_sources)
        seen_contents = {s.get("content", "") for s in existing_sources}

        label = "CRAG 补充检索中..." if is_corrective else "知识库检索中..."
        call_id = f"lg_retrieve_{state.get('iteration', 0)}"
        self._emit("state_change", {"state": "tool_calling", "label": label})
        self._emit("tool_call", {"tool": "knowledge_search", "args": {"query": query}, "call_id": call_id})

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
                "tool": "knowledge_search", "call_id": call_id,
                "result": {"error": str(e), "found": False}, "latency_ms": retrieve_span.latency_ms,
            })
            return {"retrieval_sources": [], "retrieval_context": state.get("retrieval_context", "")}

        sources = rag_result.get("sources", [])
        formatted = []
        per_budget = 3000 // max(len(sources), 1)
        for s in sources:
            content = (s.get("content") or "").strip()
            if len(content) > per_budget:
                content = content[:per_budget] + "..."
            # 补充检索时跳过与首轮重复的 chunk
            if content in seen_contents:
                continue
            seen_contents.add(content)
            formatted.append({
                "index": index_offset + len(formatted) + 1,
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

        retrieve_span.finish(output={"source_count": len(formatted), "corrective": is_corrective})
        self._emit("tool_result", {
            "tool": "knowledge_search", "call_id": call_id,
            "result": tool_result_data, "latency_ms": retrieve_span.latency_ms,
        })

        graph_context = rag_result.get("graph_context", "")
        if graph_context:
            context += f"\n\n【知识图谱补充】\n{graph_context}"

        prev_context = state.get("retrieval_context", "")
        if prev_context and context:
            context = f"{prev_context}\n\n【CRAG 补充检索】\n{context}"
        elif prev_context:
            context = prev_context

        return {"retrieval_sources": formatted, "retrieval_context": context}

    # ── Grade (CRAG 文档质量评估，发生在生成之前) ──

    async def _node_grade_documents(self, state: OrchestratorState) -> dict:
        sources = state.get("retrieval_sources", [])
        iteration = state.get("iteration", 0)

        if not settings.crag_enabled:
            return {"sufficient": True}

        grade_span = self.trace.create_span(
            "grade_documents", span_type="grading",
            input_data={"source_count": len(sources), "iteration": iteration},
        )
        self._emit("state_change", {"state": "reflecting", "label": "评估检索结果质量..."})

        sufficient, reason = self._heuristic_grade(sources)

        # 可选：LLM 文档相关性打分（temperature=0，单次调用批量判定）。
        # 只在启发式认为「足够」时做二次确认，避免低分结果白白多花一次 LLM 调用。
        if sufficient and settings.crag_llm_grader:
            try:
                llm_sufficient, llm_reason = await self._llm_grade(state["query"], sources)
                if not llm_sufficient:
                    sufficient, reason = False, llm_reason
            except Exception as e:
                logger.warning(f"[CRAG:grade] LLM 打分失败，沿用启发式结论: {e}")

        can_retry = iteration < settings.crag_max_retries
        triggered = (not sufficient) and can_retry

        grade_span.finish(output={"sufficient": sufficient, "reason": reason, "will_correct": triggered})

        if triggered:
            logger.info(f"[CRAG] 检索结果不足（{reason}），触发纠错检索 (iteration={iteration})")
            self._emit("state_change", {
                "state": "reflecting",
                "label": f"检索质量评估：{reason} → 触发 CRAG 纠错检索",
            })
        elif not sufficient:
            # 纠错次数用尽，带着现有资料生成，由 prompt 中的「依据不足需声明」规则兜底
            self._emit("state_change", {
                "state": "reflecting",
                "label": "补充检索后资料仍有限，基于现有资料回答",
            })
        else:
            self._emit("state_change", {
                "state": "reflecting",
                "label": f"检索质量评估通过（{len(sources)} 条来源）",
            })

        return {
            "sufficient": sufficient,
            "crag_triggered": state.get("crag_triggered", False) or triggered,
        }

    @staticmethod
    def _heuristic_grade(sources: List[Dict[str, Any]]) -> tuple:
        """基于检索管线自身分数的确定性评估：零额外开销、结果可复现。"""
        if len(sources) < settings.crag_min_sources:
            return False, f"命中来源不足（{len(sources)} < {settings.crag_min_sources}）"
        top_score = max(s.get("similarity", 0) for s in sources)
        if top_score < settings.crag_score_threshold:
            return False, f"最高相关度 {top_score:.2f} 低于阈值 {settings.crag_score_threshold}"
        return True, f"top1 相关度 {top_score:.2f}"

    async def _llm_grade(self, query: str, sources: List[Dict[str, Any]]) -> tuple:
        """单次 LLM 调用批量判定 top 文档与问题的相关性（temperature=0 保证稳定）。"""
        docs = sources[: settings.crag_llm_grader_top_k]
        doc_block = "\n\n".join(
            f"[文档{i + 1}] {s.get('content', '')[:400]}" for i, s in enumerate(docs)
        )
        prompt = (
            "你是检索质量评估器。逐个判断以下文档是否包含回答用户问题所需的信息。\n"
            "只输出 JSON 数组，每个元素为 true 或 false，与文档顺序一一对应，"
            f"例如 [true, false, true]。不要输出其他内容。\n\n用户问题：{query}\n\n{doc_block}"
        )
        client = self.llm_client._get_client()
        resp = await client.chat.completions.create(
            model=self.llm_client.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        start, end = text.find("["), text.rfind("]") + 1
        verdicts = json.loads(text[start:end]) if 0 <= start < end else []
        relevant = sum(1 for v in verdicts if v is True)
        if relevant < settings.crag_min_sources:
            return False, f"LLM 判定仅 {relevant}/{len(docs)} 条文档相关"
        return True, f"LLM 判定 {relevant}/{len(docs)} 条文档相关"

    # ── Transform Query (CRAG 纠错：改写查询后重新检索) ──

    async def _node_transform_query(self, state: OrchestratorState) -> dict:
        iteration = state.get("iteration", 0)
        self._emit("state_change", {"state": "tool_calling", "label": "改写查询关键词，准备补充检索..."})
        transform_span = self.trace.create_span(
            "transform_query", span_type="llm_call", input_data={"iteration": iteration},
        )

        original = state["query"]
        current = state.get("search_query") or original
        new_query = original

        try:
            from app.services.rag.query_rewriter import rewrite_query
            rewrites = await rewrite_query(original, n_rewrites=2)
            # rewrite_query 返回 [原query, 改写1, 改写2...]，取第一个尚未用过的改写
            for candidate in rewrites:
                if candidate not in (original, current):
                    new_query = candidate
                    break
        except Exception as e:
            logger.warning(f"[CRAG:transform] 查询改写失败，沿用原始查询: {e}")

        transform_span.finish(output={"new_query": new_query})
        logger.info(f"[CRAG] 查询改写: '{current[:30]}' → '{new_query[:30]}'")
        return {"search_query": new_query, "iteration": iteration + 1}

    # ── Synthesize (整个图中唯一的生成节点，只执行一次，全程流式) ──

    async def _node_synthesize(self, state: OrchestratorState) -> dict:
        if state.get("crag_triggered"):
            self._emit("state_change", {"state": "responding", "label": "CRAG 补充检索完成，生成回答中..."})
        else:
            self._emit("state_change", {"state": "responding", "label": "生成回答中..."})

        combined = state.get("retrieval_context", "")

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

    # ── Routing ──

    def _route_after_grade(self, state: OrchestratorState) -> str:
        if state.get("sufficient", True):
            return "synthesize"
        if state.get("iteration", 0) >= settings.crag_max_retries:
            return "synthesize"
        return "transform"

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
            "search_query": "",
            "conversation_messages": conversation_messages or [],
            "system_prompt": system_prompt,
            "retrieval_sources": [],
            "retrieval_context": "",
            "answer": "",
            "grounded_ratio": 0.0,
            "grounding_detail": {},
            "sufficient": True,
            "crag_triggered": False,
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
            "crag_iterations": final_state.get("iteration", 0),
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
