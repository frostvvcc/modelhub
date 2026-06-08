"""
LangGraph 多 Agent 编排器 — 基于 CRAG (Corrective RAG) 的状态图编排

使用 LangGraph StateGraph 实现可视化、可检查点的多 Agent 工作流：
  classify → retrieve / analyze (并行) → synthesize → verify → [corrective_retrieve] → END

相比手写状态机的优势：
  - 图结构可序列化、可可视化（Mermaid 导出）
  - 内置 checkpointing，支持 human-in-the-loop 断点续跑
  - 条件边实现 CRAG 闭环：验证不通过 → 补充检索 → 重新合成

参考:
  - Yan et al., "Corrective Retrieval Augmented Generation", 2024
  - LangGraph Documentation: https://langchain-ai.github.io/langgraph/
"""
import asyncio
import json
import logging
from typing import List, Dict, Any, Optional, TypedDict, Annotated
from enum import Enum

from langgraph.graph import StateGraph, END

from app.services.agent.engine import AgentEvent
from app.config import settings

logger = logging.getLogger(__name__)


# ── State Schema ──

class AgentRole(str, Enum):
    RETRIEVAL = "retrieval"
    ANALYSIS = "analysis"


def _merge_lists(left: list, right: list) -> list:
    """Reducer: 合并两个 list（用于 LangGraph state 的 annotated reducer）"""
    return left + right


class OrchestratorState(TypedDict):
    """LangGraph 状态定义 — 在节点之间流转的共享数据"""
    query: str
    conversation_messages: List[Dict[str, str]]
    # 意图分类结果
    active_agents: List[str]
    intent_reasoning: str
    # 检索结果
    retrieval_context: str
    retrieval_sources: Annotated[List[Dict[str, Any]], _merge_lists]
    analysis_context: str
    # 合成回答
    answer: str
    answer_tokens: List[str]
    # CRAG 验证
    grounded_ratio: float
    grounding_detail: Dict[str, Any]
    crag_triggered: bool
    corrective_context: str
    # 控制流
    iteration: int
    events: Annotated[List[Dict[str, Any]], _merge_lists]


# ── Node Implementations ──

class LangGraphOrchestrator:
    """
    基于 LangGraph 的多 Agent 编排器。

    Graph 结构:
        classify → route → [retrieve, analyze] → synthesize → verify → route_verify → [END / corrective]
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

    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 状态图"""
        graph = StateGraph(OrchestratorState)

        # 添加节点
        graph.add_node("classify", self._node_classify)
        graph.add_node("retrieve", self._node_retrieve)
        graph.add_node("analyze", self._node_analyze)
        graph.add_node("synthesize", self._node_synthesize)
        graph.add_node("verify", self._node_verify)
        graph.add_node("corrective_retrieve", self._node_corrective_retrieve)

        # 入口 → 意图分类
        graph.set_entry_point("classify")

        # 意图分类 → 条件路由
        graph.add_conditional_edges(
            "classify",
            self._route_after_classify,
            {
                "retrieve_only": "retrieve",
                "analyze_only": "analyze",
                "both": "retrieve",
            },
        )

        # 检索完成后判断是否需要分析
        graph.add_conditional_edges(
            "retrieve",
            self._route_after_retrieve,
            {
                "synthesize": "synthesize",
                "analyze": "analyze",
            },
        )

        # 分析 → 合成
        graph.add_edge("analyze", "synthesize")

        # 合成 → 验证
        graph.add_edge("synthesize", "verify")

        # 验证 → 条件路由（通过 → END，不通过 → 补充检索）
        graph.add_conditional_edges(
            "verify",
            self._route_after_verify,
            {
                "pass": END,
                "corrective": "corrective_retrieve",
            },
        )

        # 补充检索 → 重新合成
        graph.add_edge("corrective_retrieve", "synthesize")

        return graph.compile()

    # ── Classify Node ──

    async def _node_classify(self, state: OrchestratorState) -> dict:
        """LLM-based 意图分类"""
        query = state["query"]

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
                            "needs_retrieval": {
                                "type": "boolean",
                                "description": "是否需要从知识库检索信息"
                            },
                            "needs_analysis": {
                                "type": "boolean",
                                "description": "是否需要查询结构化数据（统计、组织架构等）"
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "分类理由"
                            },
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
                max_tokens=150,
                temperature=0.0,
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
                return {
                    "active_agents": agents,
                    "intent_reasoning": reasoning,
                    "events": [{"type": "orchestrator_plan", "data": {"agents": agents, "reasoning": reasoning}}],
                }
        except Exception as e:
            logger.warning(f"LLM 意图分类失败: {e}")

        return {
            "active_agents": ["retrieval"],
            "intent_reasoning": "LLM 分类失败，默认检索",
            "events": [{"type": "orchestrator_plan", "data": {"agents": ["retrieval"], "reasoning": "fallback"}}],
        }

    # ── Retrieve Node ──

    async def _node_retrieve(self, state: OrchestratorState) -> dict:
        """检索子 Agent：RAG 知识检索"""
        from app.services.rag.retrieval import VectorRetriever

        query = state["query"]
        all_results = []

        for vdb_id in self.vector_db_ids[:3]:
            try:
                results = await VectorRetriever.enhanced_query(
                    vector_db_id=vdb_id, query_text=query, n_results=5,
                )
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"[LangGraph:retrieve] vdb_id={vdb_id} 失败: {e}")

        all_results.sort(key=lambda r: r.similarity, reverse=True)
        top_results = all_results[:5]

        context = "\n\n".join(
            f"[来源{i+1}] {r.content[:500]}" for i, r in enumerate(top_results)
        )
        sources = [
            {"content": r.content, "source": r.source, "similarity": r.similarity, "chunk_id": r.chunk_id}
            for r in top_results
        ]

        return {
            "retrieval_context": context,
            "retrieval_sources": sources,
            "events": [{"type": "sub_agent_done", "data": {"agent": "retrieval", "source_count": len(sources)}}],
        }

    # ── Analyze Node ──

    async def _node_analyze(self, state: OrchestratorState) -> dict:
        """分析子 Agent：结构化数据查询"""
        from app.services.agent.tools import DatabaseQueryTool

        query = state["query"]
        try:
            tool = DatabaseQueryTool(session=self.session, user_id=self.user_id)
            result = await tool.execute(query=query)
            content = str(result) if result else ""
        except Exception as e:
            content = f"数据查询失败: {e}"
            logger.warning(f"[LangGraph:analyze] 失败: {e}")

        return {
            "analysis_context": content,
            "events": [{"type": "sub_agent_done", "data": {"agent": "analysis"}}],
        }

    # ── Synthesize Node ──

    async def _node_synthesize(self, state: OrchestratorState) -> dict:
        """合成回答：基于检索和分析结果生成回答"""
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

        try:
            response = await client.chat.completions.create(
                model=self.llm_client.model,
                messages=messages,
                temperature=self.llm_client.temperature,
                max_tokens=2048,
                stream=True,
            )
            answer = ""
            tokens = []
            async for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    answer += delta.content
                    tokens.append(delta.content)

            return {
                "answer": answer,
                "answer_tokens": tokens,
                "events": [{"type": "state_change", "data": {"state": "synthesizing", "label": "合成回答完成"}}],
            }
        except Exception as e:
            logger.error(f"[LangGraph:synthesize] 失败: {e}")
            return {
                "answer": "抱歉，生成回答时出现错误。",
                "answer_tokens": [],
                "events": [{"type": "error", "data": {"message": f"合成失败: {e}"}}],
            }

    # ── Verify Node (CRAG Core) ──

    async def _node_verify(self, state: OrchestratorState) -> dict:
        """
        CRAG 验证节点：Claim-Level Grounding 验证。
        如果 grounded_ratio 低于阈值，标记需要 Corrective Retrieval。
        """
        answer = state.get("answer", "")
        sources = state.get("retrieval_sources", [])

        if not answer or not sources:
            return {
                "grounded_ratio": 1.0,
                "grounding_detail": {},
                "crag_triggered": False,
                "events": [{"type": "verification", "data": {"grounded_ratio": 1.0, "skipped": True}}],
            }

        try:
            from app.services.rag.grounding import verify_grounding
            source_texts = [s.get("content", "") for s in sources if s.get("content")]
            grounding_result = await verify_grounding(answer, source_texts)

            ratio = grounding_result.get("grounded_ratio", 1.0)
            threshold = settings.grounding_threshold
            needs_correction = ratio < threshold and state.get("iteration", 0) < self.MAX_CRAG_ITERATIONS

            if needs_correction:
                logger.info(
                    f"[CRAG] grounded_ratio={ratio:.2f} < {threshold}, "
                    f"触发 Corrective Retrieval (iteration={state.get('iteration', 0)})"
                )

            return {
                "grounded_ratio": ratio,
                "grounding_detail": grounding_result,
                "crag_triggered": needs_correction,
                "iteration": state.get("iteration", 0) + 1,
                "events": [{"type": "verification", "data": {
                    "grounded_ratio": ratio,
                    "total_claims": grounding_result.get("total_claims", 0),
                    "supported_count": grounding_result.get("supported_count", 0),
                    "crag_triggered": needs_correction,
                }}],
            }
        except Exception as e:
            logger.warning(f"[LangGraph:verify] Grounding 失败: {e}")
            return {
                "grounded_ratio": 0.0,
                "grounding_detail": {"error": str(e)},
                "crag_triggered": False,
                "events": [{"type": "verification", "data": {"grounding_skipped": True, "reason": str(e)}}],
            }

    # ── Corrective Retrieve Node ──

    async def _node_corrective_retrieve(self, state: OrchestratorState) -> dict:
        """
        CRAG 补充检索：对验证不通过的 claim 进行定向 GraphRAG 检索。
        """
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
            for vdb_id in self.vector_db_ids[:2]:
                triples = await asyncio.to_thread(query_subgraph, entities, vdb_id)
                all_triples.extend(triples)

            context = format_triples_for_context(all_triples)

            return {
                "corrective_context": context,
                "events": [{"type": "state_change", "data": {
                    "state": "corrective_retrieval",
                    "label": f"CRAG 补充检索: {len(all_triples)} 条三元组",
                }}],
            }
        except Exception as e:
            logger.warning(f"[LangGraph:corrective] 补充检索失败: {e}")
            return {"corrective_context": "", "events": []}

    # ── Routing Functions ──

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

    # ── Public API ──

    async def run(
        self,
        query: str,
        conversation_messages: Optional[List[Dict[str, str]]] = None,
    ):
        """
        执行 LangGraph 编排，yield AgentEvent 流。
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
            "answer_tokens": [],
            "grounded_ratio": 0.0,
            "grounding_detail": {},
            "crag_triggered": False,
            "corrective_context": "",
            "iteration": 0,
            "events": [],
        }

        final_state = await self._graph.ainvoke(initial_state)

        # Yield accumulated events
        for event_data in final_state.get("events", []):
            yield AgentEvent(type=event_data["type"], data=event_data["data"])

        # Yield answer tokens for streaming
        for token in final_state.get("answer_tokens", []):
            yield AgentEvent(type="token", data={"content": token})

        # Final done event
        yield AgentEvent(type="done", data={
            "content": final_state.get("answer", ""),
            "sources": final_state.get("retrieval_sources", []),
            "agents_used": final_state.get("active_agents", []),
            "grounded_ratio": final_state.get("grounded_ratio", 0.0),
            "crag_triggered": final_state.get("crag_triggered", False),
        })

    def get_graph_mermaid(self) -> str:
        """导出 Mermaid 图表，用于文档和可视化"""
        try:
            return self._graph.get_graph().draw_mermaid()
        except Exception:
            return ""
