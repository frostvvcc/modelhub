"""
CRAG (Corrective RAG) 多 Agent 编排器

执行流程（run() 手动编排各节点，实现合成阶段真正流式输出）：
  classify → retrieve / analyze → stream_synthesize → verify → [corrective_retrieve → re-synthesize]

CRAG 闭环：verify 不通过 → GraphRAG 补充检索 → 重新流式合成

参考: Yan et al., "Corrective Retrieval Augmented Generation", 2024
"""
import asyncio
import json
import logging
from typing import List, Dict, Any, Optional

from app.services.agent.engine import AgentEvent
from app.config import settings

logger = logging.getLogger(__name__)


class LangGraphOrchestrator:
    """
    CRAG 多 Agent 编排器。

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
            from app.database_async import AsyncSessionLocal
            async with AsyncSessionLocal() as _analyze_db:
                tool = DatabaseQueryTool(session=_analyze_db, user_id=self.user_id)
                result = await tool.execute(query=query)
            content = str(result) if result else ""
        except Exception as e:
            content = f"数据查询失败: {e}"
            logger.warning(f"[LangGraph:analyze] 失败: {e}")

        return {
            "analysis_context": content,
            "events": [{"type": "sub_agent_done", "data": {"agent": "analysis"}}],
        }

    # _node_synthesize 已删除 — 合成阶段由 _stream_synthesize 实现真正流式输出

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
            grounding_result = await verify_grounding(answer, sources)

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

    # ── Streaming Synthesis ──

    async def _stream_synthesize(self, state: dict):
        """流式合成：逐 token yield，供 run() 实时推送给前端"""
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
                    yield delta.content
        except Exception as e:
            logger.error(f"[LangGraph:synthesize] 流式合成失败: {e}")
            fallback = "抱歉，生成回答时出现错误。"
            answer = fallback
            yield fallback

        state["answer"] = answer

    # ── Public API ──

    async def run(
        self,
        query: str,
        conversation_messages: Optional[List[Dict[str, str]]] = None,
    ):
        """
        执行 LangGraph 编排，分阶段 yield AgentEvent 流。

        Phase 1: classify + retrieve + analyze（非流式，快速完成）
        Phase 2: synthesize（真正流式，逐 token yield）
        Phase 3: CRAG verify（验证不通过则 corrective retrieve + 重新流式合成）
        """
        state: dict = {
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

        # ── Phase 1: Classify + Retrieve + Analyze ──
        yield AgentEvent(type="state_change", data={"state": "classifying", "label": "意图分类中..."})
        classify_result = await self._node_classify(state)
        state.update(classify_result)
        for ev in classify_result.get("events", []):
            yield AgentEvent(type=ev["type"], data=ev["data"])

        agents = state.get("active_agents", ["retrieval"])

        if "retrieval" in agents:
            yield AgentEvent(type="state_change", data={"state": "retrieving", "label": "检索知识库..."})
            retrieve_result = await self._node_retrieve(state)
            state.update(retrieve_result)
            for ev in retrieve_result.get("events", []):
                yield AgentEvent(type=ev["type"], data=ev["data"])

        if "analysis" in agents:
            yield AgentEvent(type="state_change", data={"state": "analyzing", "label": "查询结构化数据..."})
            analyze_result = await self._node_analyze(state)
            state.update(analyze_result)
            for ev in analyze_result.get("events", []):
                yield AgentEvent(type=ev["type"], data=ev["data"])

        # 检索完成后先发 sources
        if state.get("retrieval_sources"):
            yield AgentEvent(type="sources", data=state["retrieval_sources"])

        # ── Phase 2: Streaming Synthesis ──
        yield AgentEvent(type="state_change", data={"state": "responding", "label": "生成回答中..."})
        async for token in self._stream_synthesize(state):
            yield AgentEvent(type="token", data={"content": token})

        # ── Phase 3: CRAG Verification Loop ──
        for _ in range(self.MAX_CRAG_ITERATIONS):
            yield AgentEvent(type="state_change", data={"state": "verifying", "label": "验证回答可靠性..."})
            verify_result = await self._node_verify(state)
            state.update(verify_result)
            for ev in verify_result.get("events", []):
                yield AgentEvent(type=ev["type"], data=ev["data"])

            if not state.get("crag_triggered", False):
                break

            yield AgentEvent(type="state_change", data={"state": "corrective_retrieval", "label": "补充检索中..."})
            corrective_result = await self._node_corrective_retrieve(state)
            state.update(corrective_result)
            for ev in corrective_result.get("events", []):
                yield AgentEvent(type=ev["type"], data=ev["data"])

            yield AgentEvent(type="state_change", data={"state": "responding", "label": "重新生成回答..."})
            state["answer"] = ""
            async for token in self._stream_synthesize(state):
                yield AgentEvent(type="token", data={"content": token})

        # ── Final Done ──
        yield AgentEvent(type="done", data={
            "content": state.get("answer", ""),
            "sources": state.get("retrieval_sources", []),
            "agents_used": state.get("active_agents", []),
            "grounded_ratio": state.get("grounded_ratio", 0.0),
            "crag_triggered": state.get("crag_triggered", False),
        })

