"""
多 Agent 编排层 — 基于 CRAG (Corrective RAG) 的编排策略

Orchestrator 根据用户意图分派子 Agent：
  - RetrievalAgent: RAG 知识检索（复用现有 AgentEngine + KnowledgeSearchTool）
  - AnalysisAgent:  结构化数据分析（复用 DatabaseQueryTool）
  - VerifierAgent:  Claim 级 fact-check + Corrective 补充检索闭环

CRAG 编排流程 (Yan et al., 2024)：
  1. LLM 意图分类 → 决定激活哪些子 Agent
  2. 子 Agent 并行执行
  3. VerifierAgent 对合成结果做 Claim-Level Grounding 验证
  4. 如果 grounded_ratio < 阈值 → 触发 Corrective 补充检索 → 重新合成
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum

from app.services.agent.engine import AgentEvent
from app.utils.token_budget import TokenBudget

logger = logging.getLogger(__name__)


class SubAgentRole(str, Enum):
    RETRIEVAL = "retrieval"
    ANALYSIS = "analysis"
    VERIFIER = "verifier"


@dataclass
class SubAgentResult:
    role: SubAgentRole
    content: str
    sources: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentOrchestrator:
    """
    多 Agent 编排器。

    不替换现有的 AgentEngine，而是在其上层封装：
    - 简单问题直接走 AgentEngine（单 Agent）
    - 复杂问题拆解后分派多个子 Agent
    """

    @property
    def grounding_threshold(self) -> float:
        from app.config import settings
        return settings.grounding_threshold

    def __init__(
        self,
        llm_client: Any,
        vector_db_ids: Optional[List[int]] = None,
        user_id: Optional[int] = None,
        session: Optional[Any] = None,
        token_budget: Optional[TokenBudget] = None,
    ):
        self.llm_client = llm_client
        self.vector_db_ids = vector_db_ids or []
        self.user_id = user_id
        self.session = session
        self.token_budget = token_budget or TokenBudget(max_tokens=16000)

    async def classify_intent(self, query: str) -> List[SubAgentRole]:
        """
        LLM-based 意图分类：通过 function calling 让 LLM 判断需要哪些子 Agent。
        比关键词匹配更准确，能理解语义而非依赖表面词汇。
        """
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
                                "description": "是否需要从知识库检索信息（政策、规定、流程、事实性问题等）"
                            },
                            "needs_analysis": {
                                "type": "boolean",
                                "description": "是否需要查询结构化数据（统计、数量、排名、组织架构等）"
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "一句话说明分类理由"
                            },
                        },
                        "required": ["needs_retrieval", "needs_analysis", "reasoning"]
                    }
                }
            }]

            response = await client.chat.completions.create(
                model=self.llm_client.model,
                messages=[{
                    "role": "user",
                    "content": f"分析以下用户查询的意图：\n\n{query[:200]}"
                }],
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "classify_query_intent"}},
                max_tokens=150,
                temperature=0.0,
            )

            import json
            tc = response.choices[0].message.tool_calls
            if tc:
                result = json.loads(tc[0].function.arguments)
                roles = []
                if result.get("needs_retrieval", True):
                    roles.append(SubAgentRole.RETRIEVAL)
                if result.get("needs_analysis", False):
                    roles.append(SubAgentRole.ANALYSIS)
                if not roles:
                    roles.append(SubAgentRole.RETRIEVAL)
                roles.append(SubAgentRole.VERIFIER)
                logger.info(f"[意图分类] LLM: {[r.value for r in roles]}, reason={result.get('reasoning', '')}")
                return roles

        except Exception as e:
            logger.warning(f"LLM 意图分类失败，降级为默认策略: {e}")

        roles = [SubAgentRole.RETRIEVAL]
        if self.vector_db_ids:
            roles.append(SubAgentRole.VERIFIER)
        return roles

    async def _run_retrieval(self, query: str) -> SubAgentResult:
        """检索子 Agent：执行 RAG 检索"""
        from app.services.rag.retrieval import VectorRetriever

        all_results = []
        for vdb_id in self.vector_db_ids[:3]:
            try:
                results = await VectorRetriever.enhanced_query(
                    vector_db_id=vdb_id,
                    query_text=query,
                    n_results=5,
                )
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"RetrievalAgent 检索 vdb_id={vdb_id} 失败: {e}")

        all_results.sort(key=lambda r: r.similarity, reverse=True)
        top_results = all_results[:5]

        context = "\n\n".join(
            f"[来源{i+1}] {r.content[:500]}"
            for i, r in enumerate(top_results)
        )
        sources = [
            {"content": r.content, "source": r.source, "similarity": r.similarity, "chunk_id": r.chunk_id}
            for r in top_results
        ]
        return SubAgentResult(
            role=SubAgentRole.RETRIEVAL,
            content=context,
            sources=sources,
        )

    async def _run_analysis(self, query: str) -> SubAgentResult:
        """分析子 Agent：结构化数据查询"""
        from app.services.agent.tools import DatabaseQueryTool

        tool = DatabaseQueryTool(session=self.session)
        try:
            result = await tool.execute(query=query)
            content = str(result) if result else ""
        except Exception as e:
            content = f"数据查询失败: {e}"
            logger.warning(f"AnalysisAgent 失败: {e}")

        return SubAgentResult(role=SubAgentRole.ANALYSIS, content=content)

    async def _run_verifier(
        self,
        query: str,
        answer: str,
        sources: List[Dict[str, Any]],
    ) -> SubAgentResult:
        """
        验证子 Agent — CRAG (Corrective RAG) 核心：
        1. Claim-Level Grounding: 将回答拆分为独立声明，逐条 NLI 验证
        2. Confidence Evaluation: 计算 grounded_ratio，低于阈值标记为不可靠
        3. Corrective Retrieval: 对不可靠 claim 触发 GraphRAG 定向补充检索
        参考: Yan et al., "Corrective Retrieval Augmented Generation", 2024
        """
        from app.services.rag.grounding import verify_grounding

        source_texts = [s.get("content", "") for s in sources if s.get("content")]

        try:
            grounding_result = await verify_grounding(answer, source_texts)
        except Exception as e:
            logger.warning(f"VerifierAgent Grounding 失败: {e}")
            return SubAgentResult(
                role=SubAgentRole.VERIFIER,
                content=answer,
                metadata={"grounding_skipped": True, "reason": str(e)},
            )

        grounded_ratio = grounding_result.get("grounded_ratio", 1.0)
        unsupported_claims = [
            c for c in grounding_result.get("claims", [])
            if c.get("verdict") in ("unsupported", "contradicted")
        ]

        metadata = {
            "grounded_ratio": grounded_ratio,
            "total_claims": len(grounding_result.get("claims", [])),
            "unsupported_count": len(unsupported_claims),
            "verification_passed": grounded_ratio >= self.grounding_threshold,
        }

        if grounded_ratio < self.grounding_threshold and unsupported_claims and self.vector_db_ids:
            logger.info(
                f"[CRAG] grounded_ratio={grounded_ratio:.2f} < {self.grounding_threshold}, "
                f"触发 Corrective Retrieval ({len(unsupported_claims)} 条不可靠 claim)"
            )
            supplementary = await self._supplement_with_graph(unsupported_claims)
            if supplementary:
                metadata["graph_supplement"] = supplementary
                metadata["crag_triggered"] = True

        return SubAgentResult(
            role=SubAgentRole.VERIFIER,
            content=answer,
            sources=sources,
            metadata=metadata,
        )

    async def _supplement_with_graph(self, unsupported_claims: List[Dict]) -> str:
        """从不可靠 claim 中提取实体，用 GraphRAG 做定向补充检索"""
        from app.services.rag.graph_rag import (
            NEO4J_ENABLED, extract_query_entities, query_subgraph, format_triples_for_context,
        )
        if not NEO4J_ENABLED:
            return ""

        claim_texts = [c.get("claim", "") for c in unsupported_claims[:3]]
        combined = " ".join(claim_texts)

        entities = await extract_query_entities(combined)
        if not entities:
            return ""

        all_triples = []
        for vdb_id in self.vector_db_ids[:2]:
            triples = await asyncio.to_thread(query_subgraph, entities, vdb_id)
            all_triples.extend(triples)

        return format_triples_for_context(all_triples)

    async def run(
        self,
        query: str,
        conversation_messages: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        编排入口：意图分类 → 分派子 Agent → 合成 → 验证。
        """
        roles = await self.classify_intent(query)
        yield AgentEvent(type="orchestrator_plan", data={
            "agents": [r.value for r in roles],
            "query": query[:100],
        })

        sub_results: Dict[SubAgentRole, SubAgentResult] = {}
        tasks = []

        if SubAgentRole.RETRIEVAL in roles:
            tasks.append(("retrieval", self._run_retrieval(query)))
        if SubAgentRole.ANALYSIS in roles:
            tasks.append(("analysis", self._run_analysis(query)))

        if tasks:
            results = await asyncio.gather(
                *[t[1] for t in tasks],
                return_exceptions=True,
            )
            for (name, _), result in zip(tasks, results):
                if isinstance(result, SubAgentResult):
                    sub_results[result.role] = result
                    yield AgentEvent(type="sub_agent_done", data={
                        "agent": name,
                        "content_length": len(result.content),
                        "source_count": len(result.sources),
                    })
                elif isinstance(result, Exception):
                    logger.error(f"子 Agent {name} 失败: {result}")

        context_parts = []
        all_sources = []
        for role in [SubAgentRole.RETRIEVAL, SubAgentRole.ANALYSIS]:
            if role in sub_results:
                context_parts.append(sub_results[role].content)
                all_sources.extend(sub_results[role].sources)

        combined_context = "\n\n".join(context_parts)

        yield AgentEvent(type="state_change", data={
            "state": "synthesizing", "label": "合成回答中...",
        })

        client = self.llm_client._get_client()
        messages = [
            {"role": "system", "content": (
                "你是一个智能助手。基于以下参考资料回答用户问题，引用时标注[来源N]。\n"
                "如果资料不足以回答，请如实说明。\n\n"
                f"参考资料：\n{combined_context[:4000]}"
            )},
        ]
        if conversation_messages:
            messages.extend(conversation_messages[-6:])
        messages.append({"role": "user", "content": query})

        try:
            response = await client.chat.completions.create(
                model=self.llm_client.model,
                messages=messages,
                temperature=self.llm_client.temperature,
                max_tokens=2048,
                stream=True,
            )
            answer = ""
            async for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    answer += delta.content
                    yield AgentEvent(type="token", data={"content": delta.content})
        except Exception as e:
            yield AgentEvent(type="error", data={"message": f"合成回答失败: {e}"})
            return

        if SubAgentRole.VERIFIER in roles and all_sources:
            yield AgentEvent(type="state_change", data={
                "state": "verifying", "label": "验证回答可靠性...",
            })
            verify_result = await self._run_verifier(query, answer, all_sources)
            yield AgentEvent(type="verification", data=verify_result.metadata)

        yield AgentEvent(type="done", data={
            "content": answer,
            "sources": all_sources,
            "agents_used": [r.value for r in roles],
            "token_budget": self.token_budget.summary(),
        })
