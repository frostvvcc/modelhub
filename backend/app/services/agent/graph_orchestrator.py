"""
LangGraph CRAG (Corrective RAG) 多 Agent 编排器

使用 LangGraph StateGraph 驱动的多 Agent 工作流：
  classify → retrieve / analyze → synthesize(流式) → verify → [corrective_retrieve → re-synthesize]

合成节点通过 get_stream_writer() 实现真正的逐 token 流式输出，
同时保持 LangGraph 图引擎的状态管理和条件路由能力。

参考:
  - Yan et al., "Corrective Retrieval Augmented Generation", 2024
  - LangGraph Documentation: https://langchain-ai.github.io/langgraph/
"""
import asyncio
import json
import logging
from typing import List, Dict, Any, Optional, TypedDict, Annotated

from langgraph.graph import StateGraph, END
from langgraph.config import get_stream_writer

from app.services.agent.engine import AgentEvent
from app.config import settings

logger = logging.getLogger(__name__)


# ── State Schema ──

def _merge_lists(left: list, right: list) -> list:
    return left + right


class OrchestratorState(TypedDict):
    query: str
    conversation_messages: List[Dict[str, str]]
    active_agents: List[str]
    intent_reasoning: str
    retrieval_context: str
    retrieval_sources: Annotated[List[Dict[str, Any]], _merge_lists]
    analysis_context: str
    answer: str
    grounded_ratio: float
    grounding_detail: Dict[str, Any]
    crag_triggered: bool
    corrective_context: str
    iteration: int
    events: Annotated[List[Dict[str, Any]], _merge_lists]


# ── Orchestrator ──

class LangGraphOrchestrator:
    """
    基于 LangGraph StateGraph 的 CRAG 编排器。

    图结构:
      classify → route → [retrieve → (analyze?)] → synthesize → verify → [END / corrective → synthesize]

    合成节点使用 get_stream_writer() 逐 token 推送，
    run() 通过 astream(stream_mode=['updates','custom']) 同时拿到图状态和流式 token。
    """

    MAX_CRAG_ITERATIONS = 2

    def __init__(
        self,
        llm_client: Any,
        vector_db_ids: Optional[List[int]] = None,
        user_id: Optional[int] = None,
        session: Optional[Any] = None,
    ):
        self.llm_client = llm_client
        self.vector_db_ids = vector_db_ids or []
        self.user_id = user_id
        self.session = session
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(OrchestratorState)

        graph.add_node("classify", self._node_classify)
        graph.add_node("retrieve", self._node_retrieve)
        graph.add_node("analyze", self._node_analyze)
        graph.add_node("synthesize", self._node_synthesize)
        graph.add_node("verify", self._node_verify)
        graph.add_node("corrective_retrieve", self._node_corrective_retrieve)

        graph.set_entry_point("classify")

        graph.add_conditional_edges("classify", self._route_after_classify, {
            "retrieve_only": "retrieve",
            "analyze_only": "analyze",
            "both": "retrieve",
        })
        graph.add_conditional_edges("retrieve", self._route_after_retrieve, {
            "synthesize": "synthesize",
            "analyze": "analyze",
        })
        graph.add_edge("analyze", "synthesize")
        graph.add_edge("synthesize", "verify")
        graph.add_conditional_edges("verify", self._route_after_verify, {
            "pass": END,
            "corrective": "corrective_retrieve",
        })
        graph.add_edge("corrective_retrieve", "synthesize")

        return graph.compile()

    # ── Routing ──

    def _route_after_classify(self, state: OrchestratorState) -> str:
        agents = state.get("active_agents", ["retrieval"])
        if "retrieval" in agents and "analysis" in agents:
            return "both"
        if "analysis" in agents:
            return "analyze_only"
        return "retrieve_only"

    def _route_after_retrieve(self, state: OrchestratorState) -> str:
        if "analysis" in state.get("active_agents", []):
            return "analyze"
        return "synthesize"

    def _route_after_verify(self, state: OrchestratorState) -> str:
        if state.get("crag_triggered", False):
            return "corrective"
        return "pass"

    # ── Classify Node ──

    async def _node_classify(self, state: OrchestratorState) -> dict:
        writer = get_stream_writer()
        query = state["query"]

        writer({"type": "state_change", "state": "classifying", "label": "意图分类中..."})

        try:
            client = self.llm_client._get_client()
            tools = [{
                "type": "function",
                "function": {
                    "name": "classify_query_intent",
                    "description": "分析用户查询的意图，判断需要哪些处理路径",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "needs_retrieval": {"type": "boolean", "description": "是否需要从知识库检索信息"},
                            "needs_analysis": {"type": "boolean", "description": "是否需要查询结构化数据"},
                            "reasoning": {"type": "string", "description": "分类理由"},
                        },
                        "required": ["needs_retrieval", "needs_analysis", "reasoning"]
                    }
                }
            }]

            response = await client.chat.completions.create(
                model=self.llm_client.model,
                messages=[{"role": "user", "content": f"分析以下查询的意图：\n\n{query[:200]}"}],
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "classify_query_intent"}},
                max_tokens=150, temperature=0.0,
            )

            tc = response.choices[0].message.tool_calls
            if tc:
                result = json.loads(tc[0].function.arguments)
                agents = []
                if result.get("needs_retrieval", True):
                    agents.append("retrieval")
                if result.get("needs_analysis", False):
                    agents.append("analysis")
                if not agents:
                    agents.append("retrieval")
                reasoning = result.get("reasoning", "")
                logger.info(f"[LangGraph:classify] agents={agents}, reason={reasoning}")
                writer({"type": "orchestrator_plan", "agents": agents, "reasoning": reasoning})
                return {"active_agents": agents, "intent_reasoning": reasoning, "events": []}
        except Exception as e:
            logger.warning(f"LLM 意图分类失败: {e}")

        writer({"type": "orchestrator_plan", "agents": ["retrieval"], "reasoning": "fallback"})
        return {"active_agents": ["retrieval"], "intent_reasoning": "fallback", "events": []}

    # ── Retrieve Node ──

    async def _select_relevant_vdb_ids(self, query: str, max_count: int = 5) -> List[int]:
        """语义选库：用 query 与知识库名称/描述的 embedding 相似度选 top-N，毫秒级。"""
        if len(self.vector_db_ids) <= max_count:
            return self.vector_db_ids

        from app.utils.async_embedding import get_query_embedding_async
        from app.database_async import AsyncSessionLocal
        from app.mapper.async_mapper import AsyncVectorMapper

        query_emb = await get_query_embedding_async(query)

        async with AsyncSessionLocal() as session:
            scored = []
            for vdb_id in self.vector_db_ids:
                vdb = await AsyncVectorMapper.get_vector_db(session, vdb_id)
                if not vdb:
                    continue
                desc_text = f"{vdb.name or ''} {vdb.describe or ''}"
                desc_emb = await get_query_embedding_async(desc_text)
                dot = sum(a * b for a, b in zip(query_emb, desc_emb))
                norm_a = sum(a * a for a in query_emb) ** 0.5
                norm_b = sum(b * b for b in desc_emb) ** 0.5
                sim = dot / (norm_a * norm_b) if norm_a and norm_b else 0.0
                scored.append((sim, vdb_id, vdb.name))
            scored.sort(key=lambda x: x[0], reverse=True)

        selected = scored[:max_count]
        logger.info(
            f"🔀 [LangGraph Router] {len(self.vector_db_ids)} 库 → {len(selected)} 库 | "
            + ", ".join(f"{name}({sim:.3f})" for sim, _, name in selected)
        )
        return [vdb_id for _, vdb_id, _ in selected]

    async def _node_retrieve(self, state: OrchestratorState) -> dict:
        writer = get_stream_writer()
        writer({"type": "state_change", "state": "retrieving", "label": "检索知识库..."})

        from app.services.rag.retrieval import VectorRetriever

        query = state["query"]
        all_results = []

        selected_ids = await self._select_relevant_vdb_ids(query, max_count=5)

        async def _query_one(vdb_id: int):
            try:
                return await VectorRetriever.enhanced_query(
                    vector_db_id=vdb_id, query_text=query, n_results=5,
                )
            except Exception as e:
                logger.warning(f"[LangGraph:retrieve] vdb_id={vdb_id} 失败: {e}")
                return []

        batch_results = await asyncio.gather(*[_query_one(v) for v in selected_ids])
        for results in batch_results:
            all_results.extend(results)

        all_results.sort(key=lambda r: r.similarity, reverse=True)
        top_results = all_results[:5]

        context = "\n\n".join(f"[来源{i+1}] {r.content[:500]}" for i, r in enumerate(top_results))
        sources = [
            {"content": r.content, "source": r.source, "similarity": r.similarity, "chunk_id": r.chunk_id}
            for r in top_results
        ]

        writer({"type": "sub_agent_done", "agent": "retrieval", "source_count": len(sources)})
        writer({"type": "sources", "data": sources})

        return {"retrieval_context": context, "retrieval_sources": sources, "events": []}

    # ── Analyze Node ──

    async def _node_analyze(self, state: OrchestratorState) -> dict:
        writer = get_stream_writer()
        writer({"type": "state_change", "state": "analyzing", "label": "查询结构化数据..."})

        from app.services.agent.tools import DatabaseQueryTool
        query = state["query"]
        try:
            from app.database_async import AsyncSessionLocal
            async with AsyncSessionLocal() as _analyze_db:
                tool = DatabaseQueryTool(session=_analyze_db, user_id=self.user_id)
                result = await tool.execute(query=query)
            content = str(result) if result else ""
        except Exception as e:
            content = f"数据查询失败: {e}"
            logger.warning(f"[LangGraph:analyze] 失败: {e}")

        writer({"type": "sub_agent_done", "agent": "analysis"})
        return {"analysis_context": content, "events": []}

    # ── Synthesize Node (流式 via get_stream_writer) ──

    async def _node_synthesize(self, state: OrchestratorState) -> dict:
        writer = get_stream_writer()
        writer({"type": "state_change", "state": "responding", "label": "生成回答中..."})

        context_parts = []
        if state.get("retrieval_context"):
            context_parts.append(state["retrieval_context"])
        if state.get("analysis_context"):
            context_parts.append(state["analysis_context"])
        if state.get("corrective_context"):
            context_parts.append(f"【补充检索】\n{state['corrective_context']}")

        combined = "\n\n".join(context_parts)

        client = self.llm_client._get_client()
        messages = [
            {"role": "system", "content": (
                "你是一个智能助手。基于以下参考资料回答用户问题，引用时标注[来源N]。\n"
                "如果资料不足以回答，请如实说明。\n\n"
                f"参考资料：\n{combined[:4000]}"
            )},
        ]
        if state.get("conversation_messages"):
            messages.extend(state["conversation_messages"][-6:])
        messages.append({"role": "user", "content": state["query"]})

        answer = ""
        try:
            response = await client.chat.completions.create(
                model=self.llm_client.model,
                messages=messages,
                temperature=self.llm_client.temperature,
                max_tokens=2048,
                stream=True,
            )
            async for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    answer += delta.content
                    writer({"type": "token", "content": delta.content})
        except Exception as e:
            logger.error(f"[LangGraph:synthesize] 流式合成失败: {e}")
            answer = "抱歉，生成回答时出现错误。"
            writer({"type": "token", "content": answer})

        return {"answer": answer, "events": []}

    # ── Verify Node (CRAG Core) ──

    async def _node_verify(self, state: OrchestratorState) -> dict:
        writer = get_stream_writer()
        writer({"type": "state_change", "state": "verifying", "label": "验证回答可靠性..."})

        answer = state.get("answer", "")
        sources = state.get("retrieval_sources", [])

        if not answer or not sources:
            writer({"type": "verification", "grounded_ratio": 1.0, "skipped": True})
            return {"grounded_ratio": 1.0, "grounding_detail": {}, "crag_triggered": False, "events": []}

        try:
            from app.services.rag.grounding import verify_grounding
            grounding_result = await verify_grounding(answer, sources)

            ratio = grounding_result.get("grounded_ratio", 1.0)
            threshold = settings.grounding_threshold
            needs_correction = ratio < threshold and state.get("iteration", 0) < self.MAX_CRAG_ITERATIONS

            if needs_correction:
                logger.info(f"[CRAG] grounded_ratio={ratio:.2f} < {threshold}, 触发 Corrective Retrieval")

            writer({"type": "verification",
                     "grounded_ratio": ratio,
                     "total_claims": grounding_result.get("total_claims", 0),
                     "supported_count": grounding_result.get("supported_count", 0),
                     "crag_triggered": needs_correction})

            return {
                "grounded_ratio": ratio,
                "grounding_detail": grounding_result,
                "crag_triggered": needs_correction,
                "iteration": state.get("iteration", 0) + 1,
                "events": [],
            }
        except Exception as e:
            logger.warning(f"[LangGraph:verify] Grounding 失败: {e}")
            writer({"type": "verification", "grounding_skipped": True, "reason": str(e)})
            return {"grounded_ratio": 0.0, "grounding_detail": {"error": str(e)}, "crag_triggered": False, "events": []}

    # ── Corrective Retrieve Node ──

    async def _node_corrective_retrieve(self, state: OrchestratorState) -> dict:
        writer = get_stream_writer()
        writer({"type": "state_change", "state": "corrective_retrieval", "label": "CRAG 补充检索中..."})

        grounding_detail = state.get("grounding_detail", {})
        unsupported = grounding_detail.get("unsupported_claims", [])

        if not unsupported:
            return {"corrective_context": "", "events": []}

        try:
            from app.services.rag.graph_rag import (
                NEO4J_ENABLED, extract_query_entities, query_subgraph, format_triples_for_context,
            )
            if not NEO4J_ENABLED:
                return {"corrective_context": "", "events": []}

            claim_texts = [c.get("text", "") for c in unsupported[:3]]
            combined = " ".join(claim_texts)
            entities = await extract_query_entities(combined)

            if not entities:
                return {"corrective_context": "", "events": []}

            all_triples = []
            for vdb_id in self.vector_db_ids:
                triples = await asyncio.to_thread(query_subgraph, entities, vdb_id)
                all_triples.extend(triples)

            context = format_triples_for_context(all_triples)
            writer({"type": "corrective_done", "triple_count": len(all_triples)})

            return {"corrective_context": context, "events": []}
        except Exception as e:
            logger.warning(f"[LangGraph:corrective] 补充检索失败: {e}")
            return {"corrective_context": "", "events": []}

    # ── Public API ──

    async def run(
        self,
        query: str,
        conversation_messages: Optional[List[Dict[str, str]]] = None,
    ):
        """
        执行 LangGraph 图编排，yield AgentEvent 流。

        使用 astream(stream_mode=['updates','custom']) 同时接收：
        - 'custom' 事件：节点通过 get_stream_writer() 发射的 token 和状态变更
        - 'updates' 事件：图引擎的节点完成状态更新
        """
        initial_state: OrchestratorState = {
            "query": query,
            "conversation_messages": conversation_messages or [],
            "active_agents": [],
            "intent_reasoning": "",
            "retrieval_context": "",
            "retrieval_sources": [],
            "analysis_context": "",
            "answer": "",
            "grounded_ratio": 0.0,
            "grounding_detail": {},
            "crag_triggered": False,
            "corrective_context": "",
            "iteration": 0,
            "events": [],
        }

        final_answer = ""
        final_sources = []
        final_agents = []
        final_grounded_ratio = 0.0
        final_crag_triggered = False

        async for mode, chunk in self._graph.astream(
            initial_state, stream_mode=["updates", "custom"]
        ):
            if mode == "custom":
                evt_type = chunk.get("type", "")
                if evt_type == "token":
                    yield AgentEvent(type="token", data={"content": chunk["content"]})
                elif evt_type == "state_change":
                    yield AgentEvent(type="state_change", data={
                        "state": chunk.get("state", ""),
                        "label": chunk.get("label", ""),
                    })
                elif evt_type == "orchestrator_plan":
                    yield AgentEvent(type="orchestrator_plan", data={
                        "agents": chunk.get("agents", []),
                        "reasoning": chunk.get("reasoning", ""),
                    })
                elif evt_type == "sub_agent_done":
                    yield AgentEvent(type="sub_agent_done", data={
                        "agent": chunk.get("agent", ""),
                        "source_count": chunk.get("source_count", 0),
                    })
                elif evt_type == "sources":
                    yield AgentEvent(type="sources", data=chunk.get("data", []))
                elif evt_type == "verification":
                    yield AgentEvent(type="verification", data=chunk)
                elif evt_type == "corrective_done":
                    yield AgentEvent(type="state_change", data={
                        "state": "corrective_retrieval",
                        "label": f"CRAG 补充检索: {chunk.get('triple_count', 0)} 条三元组",
                    })

            elif mode == "updates":
                for node_name, node_output in chunk.items():
                    if isinstance(node_output, dict):
                        if node_output.get("answer"):
                            final_answer = node_output["answer"]
                        if node_output.get("retrieval_sources"):
                            final_sources = node_output["retrieval_sources"]
                        if node_output.get("active_agents"):
                            final_agents = node_output["active_agents"]
                        if "grounded_ratio" in node_output:
                            final_grounded_ratio = node_output["grounded_ratio"]
                        if "crag_triggered" in node_output:
                            final_crag_triggered = node_output["crag_triggered"]

        yield AgentEvent(type="done", data={
            "content": final_answer,
            "sources": final_sources,
            "agents_used": final_agents,
            "grounded_ratio": final_grounded_ratio,
            "crag_triggered": final_crag_triggered,
        })
