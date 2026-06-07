"""
ReAct Agent 引擎

基于 ReAct (Reasoning + Acting) 模式的多轮工具调用循环。
用户消息 → LLM 判断是否需要调用工具
  → 需要：解析 tool_call，执行工具，把结果喂回 LLM
  → 不需要：直接回复
  → 循环直到 LLM 给出最终回答（设最大轮次兜底）
"""
import asyncio
import json
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass

from app.services.agent.tools import BaseTool, ToolSafetyLevel
from app.services.agent.state_machine import AgentStateMachine, AgentState
from app.services.agent.trace import TraceContext, Span
from app.utils.token_budget import TokenBudget, BudgetExhaustedError
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


@dataclass
class AgentEvent:
    """Agent 运行过程中产生的事件，用于 SSE 流式推送"""
    type: str
    data: Dict[str, Any]


class AgentEngine:
    """ReAct Agent 引擎"""

    # 敏感工具名 → 需要的 RBAC 权限代码
    TOOL_PERMISSION_MAP: Dict[str, str] = {
        "knowledge_write": "knowledge:write",
        "knowledge_delete": "knowledge:delete",
        "database_modify": "organization:manage",
        "user_manage": "user:manage",
    }

    def __init__(
        self,
        tools: List[BaseTool],
        max_iterations: int = 5,
        user_id: Optional[int] = None,
        session: Optional[Any] = None,
        token_budget: Optional[TokenBudget] = None,
    ):
        self.tools = {tool.name: tool for tool in tools}
        self.tool_list = tools
        self.max_iterations = max_iterations
        self.user_id = user_id
        self._session = session
        self.state_machine = AgentStateMachine()
        self.trace = TraceContext()
        self.token_budget = token_budget or TokenBudget(max_tokens=16000)

    def _get_openai_tools(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self.tool_list]

    @staticmethod
    def _safe_truncate_tool_result(result: Any, max_chars: int) -> str:
        """结构感知截断：对含 sources 的结果逐条缩减 content，保证 JSON 结构完整。"""
        json_str = json.dumps(result, ensure_ascii=False, default=str)
        if len(json_str) <= max_chars:
            return json_str

        if isinstance(result, dict) and isinstance(result.get("sources"), list):
            result = dict(result)
            result["sources"] = [dict(s) for s in result["sources"]]
            for limit in [600, 300, 150, 60]:
                for s in result["sources"]:
                    c = s.get("content", "")
                    if len(c) > limit:
                        s["content"] = c[:limit] + "..."
                json_str = json.dumps(result, ensure_ascii=False, default=str)
                if len(json_str) <= max_chars:
                    return json_str
            while len(result["sources"]) > 1:
                result["sources"].pop()
                result["count"] = len(result["sources"])
                json_str = json.dumps(result, ensure_ascii=False, default=str)
                if len(json_str) <= max_chars:
                    return json_str

        return json_str[:max_chars]

    async def run(
        self,
        messages: List[Dict[str, str]],
        llm_client: Any,
        system_messages: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        执行 ReAct 循环，yield AgentEvent 流。
        只在最终回答阶段使用流式输出，中间决策阶段用非流式，避免重复调用。
        """
        self.state_machine.transition(AgentState.PLANNING, "开始分析用户问题")
        yield AgentEvent(type="state_change", data={
            "state": AgentState.PLANNING.value,
            "label": "分析问题中...",
        })

        openai_tools = self._get_openai_tools()
        working_messages = list(system_messages or []) + list(messages)
        accumulated_content = ""
        rag_result_cache: Optional[Dict[str, Any]] = None
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1
            is_last_chance = (iteration == self.max_iterations)

            llm_span = self.trace.create_span(
                f"llm_call_{iteration}", span_type="llm_call",
                input_data={"message_count": len(working_messages), "iteration": iteration},
            )

            try:
                client = llm_client._get_client()
                all_msgs = working_messages

                response = await client.chat.completions.create(
                    model=llm_client.model,
                    messages=all_msgs,
                    tools=openai_tools if openai_tools else None,
                    temperature=llm_client.temperature,
                    top_p=llm_client.top_p,
                    max_tokens=4096,
                    stream=False,
                )

                choice = response.choices[0]
                message = choice.message

                if response.usage:
                    llm_span.tokens_used = response.usage.total_tokens
                    llm_span.prompt_tokens = response.usage.prompt_tokens
                    llm_span.completion_tokens = response.usage.completion_tokens
                    yield AgentEvent(type="token_usage", data={
                        "completion_tokens": self.trace.total_completion_tokens,
                    })
                    try:
                        self.token_budget.consume(
                            prompt_tokens=response.usage.prompt_tokens,
                            completion_tokens=response.usage.completion_tokens,
                        )
                    except BudgetExhaustedError:
                        logger.warning(f"Token 预算耗尽 (已用 {self.token_budget.used}/{self.token_budget.max_tokens})，强制进入最终回答")
                        llm_span.finish(output={"finish_reason": "budget_exhausted"})
                        break

                llm_span.finish(output={"finish_reason": choice.finish_reason})

                if choice.finish_reason == "length":
                    logger.warning(
                        f"LLM 输出被截断 (finish_reason=length)，第 {iteration} 轮，"
                        f"跳过后续工具调用，直接基于已有信息生成最终回答"
                    )
                    if self.state_machine.can_transition(AgentState.RESPONDING):
                        self.state_machine.transition(AgentState.RESPONDING, "输出截断，提前结束")
                    yield AgentEvent(type="warning", data={
                        "message": "模型输出被截断，将直接生成回答",
                        "finish_reason": "length",
                        "iteration": iteration,
                    })
                    break

                if self.token_budget.should_stop(reserve=1000):
                    logger.info(f"Token 预算剩余不足 (剩余 {self.token_budget.remaining})，跳过后续工具调用，直接回答")
                    break

            except Exception as e:
                llm_span.finish(error=str(e))
                self.state_machine.transition(AgentState.ERROR, f"LLM 调用失败: {e}")
                yield AgentEvent(type="error", data={"message": f"模型调用失败: {str(e)}"})
                self.trace.finish()
                yield AgentEvent(type="trace", data=self.trace.to_dict())
                return

            # 有 tool_calls → 执行工具
            if message.tool_calls:
                if self.state_machine.can_transition(AgentState.TOOL_CALLING):
                    self.state_machine.transition(
                        AgentState.TOOL_CALLING,
                        f"需要调用 {len(message.tool_calls)} 个工具"
                    )
                    yield AgentEvent(type="state_change", data={
                        "state": AgentState.TOOL_CALLING.value,
                        "label": "调用工具中...",
                        "tool_count": len(message.tool_calls),
                    })

                working_messages.append({
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in message.tool_calls
                    ],
                })

                if message.content:
                    yield AgentEvent(type="thinking", data={"content": message.content})

                # 预解析所有 tool_call 参数
                parsed_calls = []
                for tc in message.tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}
                    parsed_calls.append((tc, tool_name, tool_args))
                    yield AgentEvent(type="tool_call", data={
                        "tool": tool_name, "args": tool_args, "call_id": tc.id,
                    })

                # 并行执行所有工具调用（asyncio.gather），执行前按安全等级拦截
                async def _exec_tool(tc, tool_name, tool_args, parent_span=llm_span):
                    tool_span = self.trace.create_span(
                        f"tool:{tool_name}", span_type="tool_call",
                        input_data={"tool": tool_name, "args": tool_args},
                        parent=parent_span,
                    )
                    tool = self.tools.get(tool_name)
                    if not tool:
                        result = {"error": f"未知工具: {tool_name}"}
                        tool_span.finish(error=f"未知工具: {tool_name}")
                        return tc, tool_name, tool_args, result, tool_span

                    # 安全等级检查
                    if tool.safety_level == ToolSafetyLevel.DANGEROUS:
                        result = {
                            "blocked": True,
                            "reason": "该操作属于危险级别，需要用户二次确认后才能执行",
                            "tool": tool_name,
                            "args": tool_args,
                        }
                        logger.warning(f"🔴 [安全拦截] 危险工具 {tool_name} 被拦截，需要用户确认")
                        tool_span.finish(output=result)
                        return tc, tool_name, tool_args, result, tool_span

                    if tool.safety_level == ToolSafetyLevel.SENSITIVE:
                        if not self.user_id or not self._session:
                            result = {"blocked": True, "reason": "敏感操作需要用户身份验证"}
                            tool_span.finish(output=result)
                            return tc, tool_name, tool_args, result, tool_span
                        required_perm = self.TOOL_PERMISSION_MAP.get(tool_name)
                        if required_perm:
                            from app.services.permission_service import AsyncPermissionService
                            has_perm = await AsyncPermissionService.check_permission(
                                self._session, self.user_id, required_perm,
                            )
                            if not has_perm:
                                result = {"blocked": True, "reason": f"权限不足：需要 {required_perm} 权限"}
                                logger.warning(f"🟡 [安全拦截] 用户 {self.user_id} 缺少 {required_perm} 权限，工具 {tool_name} 被拦截")
                                tool_span.finish(output=result)
                                return tc, tool_name, tool_args, result, tool_span
                        logger.info(f"🟡 [安全检查] 敏感工具 {tool_name}，用户 {self.user_id} RBAC 权限校验通过")

                    try:
                        result = await tool.execute(**tool_args)
                        tool_span.finish(output=result)
                    except Exception as e:
                        result = {"error": str(e)}
                        tool_span.finish(error=str(e))
                    return tc, tool_name, tool_args, result, tool_span

                tool_results = await asyncio.gather(
                    *[_exec_tool(tc, tn, ta) for tc, tn, ta in parsed_calls]
                )

                for tc, tool_name, tool_args, result, tool_span in tool_results:
                    if tool_name == "knowledge_search" and isinstance(result, dict) and result.get("_raw_rag_result"):
                        rag_result_cache = result.pop("_raw_rag_result")

                    yield AgentEvent(type="tool_result", data={
                        "tool": tool_name, "result": result,
                        "call_id": tc.id, "latency_ms": tool_span.latency_ms,
                    })

                    max_result_chars = min(
                        max(800, self.token_budget.remaining * 2),
                        4000,
                    )
                    working_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": self._safe_truncate_tool_result(result, max_result_chars),
                    })

                if self.state_machine.can_transition(AgentState.REFLECTING):
                    self.state_machine.transition(AgentState.REFLECTING, "分析工具返回结果")
                    yield AgentEvent(type="state_change", data={
                        "state": AgentState.REFLECTING.value,
                        "label": "分析工具结果中...",
                    })

                    succeeded, failed, blocked, no_result = [], [], [], []
                    ks_sources = []
                    for _, tn, _, res, _ in tool_results:
                        if isinstance(res, dict):
                            if res.get("blocked"):
                                blocked.append(f"{tn}(权限不足: {res.get('reason', '')})")
                            elif res.get("error"):
                                failed.append(f"{tn}(错误: {res['error'][:80]})")
                            elif res.get("found") is False or res.get("count", 1) == 0:
                                no_result.append(tn)
                            else:
                                succeeded.append(tn)
                                if tn == "knowledge_search" and res.get("sources"):
                                    ks_sources = res["sources"]
                        else:
                            succeeded.append(tn)

                    reflection_parts = []
                    if ks_sources:
                        context_lines = ["【知识库检索结果 — 你必须基于以下内容回答】"]
                        for s in ks_sources:
                            idx = s.get("index", "?")
                            src = s.get("source", "未知")
                            ctx = s.get("content", "")
                            context_lines.append(f"\n[来源{idx}]（{src}）\n{ctx}")
                        context_lines.append(
                            "\n【引用规则 — 必须遵守】\n"
                            "1. 回答中每个来自上述来源的事实都必须标注来源编号，如 [来源1]，不可省略。\n"
                            "2. 来源编号必须与上面的 [来源N] 一一对应，不可编造不存在的编号。\n"
                            "3. 如果一句话的信息来自多个来源，全部标注，如 [来源1][来源3]。\n"
                            "4. 如果知识库资料不足以回答，请明确说明「当前知识库依据不足」，不要编造。"
                        )
                        working_messages.append({
                            "role": "system",
                            "content": "\n".join(context_lines),
                        })
                    if succeeded:
                        reflection_parts.append(f"成功获取结果的工具：{', '.join(succeeded)}。")
                    if no_result:
                        reflection_parts.append(f"未找到相关信息的工具：{', '.join(no_result)}。考虑改写查询关键词重试。")
                    if failed:
                        reflection_parts.append(f"执行失败的工具：{', '.join(failed)}。")
                    if blocked:
                        reflection_parts.append(f"被安全策略拦截的工具：{', '.join(blocked)}。不要再尝试调用这些工具。")
                    if ks_sources:
                        reflection_parts.append("知识库已返回结果，请直接基于上面的来源内容生成最终回答，必须标注 [来源N]。")
                    else:
                        reflection_parts.append("如果信息充分，直接生成最终回答；如果不充分，调用需要的工具补充信息。")
                    reflection_prompt = "\n".join(reflection_parts)
                    working_messages.append({
                        "role": "system",
                        "content": reflection_prompt,
                    })

                continue

            # 无 tool_calls → 最终回答，用真流式输出
            if self.state_machine.can_transition(AgentState.RESPONDING):
                self.state_machine.transition(AgentState.RESPONDING, "生成最终回答")
                yield AgentEvent(type="state_change", data={
                    "state": AgentState.RESPONDING.value,
                    "label": "生成回答中...",
                })

            # 如果本轮已有内容（LLM 直接给出文本回答），用真流式重新请求
            # 如果是第一轮且无 tool_calls，说明 LLM 认为不需要工具，直接流式输出
            final_span = self.trace.create_span(
                "llm_final_stream", span_type="llm_stream",
                input_data={"message_count": len(working_messages)},
            )
            try:
                stream = await client.chat.completions.create(
                    model=llm_client.model,
                    messages=working_messages,
                    temperature=llm_client.temperature,
                    top_p=llm_client.top_p,
                    max_tokens=4096,
                    stream=True,
                )
                token_count = 0
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        accumulated_content += delta.content
                        token_count += 1
                        yield AgentEvent(type="token", data={"content": delta.content})
                final_span.completion_tokens = token_count
                final_span.finish(output={"content_length": len(accumulated_content)})
            except Exception as e:
                final_span.finish(error=str(e))
                accumulated_content = message.content or ""
                if accumulated_content:
                    yield AgentEvent(type="token", data={"content": accumulated_content})

            break

        if iteration >= self.max_iterations and not accumulated_content:
            accumulated_content = "抱歉，经过多次尝试仍未能得到满意的结果，请尝试更具体的问题。"
            yield AgentEvent(type="token", data={"content": accumulated_content})

        if self.state_machine.can_transition(AgentState.DONE):
            self.state_machine.transition(AgentState.DONE, "回答完成")

        self.trace.finish()

        yield AgentEvent(type="done", data={
            "content": accumulated_content,
            "iterations": iteration,
            "rag_result": rag_result_cache,
            "state_machine": self.state_machine.to_dict(),
            "token_budget": self.token_budget.summary(),
        })

        yield AgentEvent(type="trace", data=self.trace.to_dict())


class SimpleStreamEngine:
    """简单流式引擎 — 不使用 Agent，直接流式输出 LLM 回答"""

    def __init__(self):
        self.trace = TraceContext()

    async def run(
        self,
        messages: List[Dict[str, str]],
        llm_client: Any,
    ) -> AsyncGenerator[AgentEvent, None]:
        yield AgentEvent(type="state_change", data={
            "state": "responding",
            "label": "生成回答中...",
        })

        span = self.trace.create_span("llm_stream", span_type="llm_stream",
                                       input_data={"message_count": len(messages)})
        accumulated = ""

        try:
            client = llm_client._get_client()
            all_msgs = messages

            stream = await client.chat.completions.create(
                model=llm_client.model,
                messages=all_msgs,
                temperature=llm_client.temperature,
                top_p=llm_client.top_p,
                max_tokens=4096,
                stream=True,
            )

            token_count = 0
            stream_usage = None
            async for chunk in stream:
                if hasattr(chunk, 'usage') and chunk.usage:
                    stream_usage = chunk.usage
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    accumulated += delta.content
                    token_count += 1
                    yield AgentEvent(type="token", data={"content": delta.content})

            if stream_usage:
                span.prompt_tokens = getattr(stream_usage, 'prompt_tokens', 0) or 0
                span.completion_tokens = getattr(stream_usage, 'completion_tokens', 0) or token_count
                span.tokens_used = getattr(stream_usage, 'total_tokens', 0) or (span.prompt_tokens + span.completion_tokens)
            else:
                from app.services.agent.memory import count_tokens
                span.completion_tokens = count_tokens(accumulated)
                prompt_text = " ".join(m.get("content", "") for m in messages if m.get("content"))
                span.prompt_tokens = count_tokens(prompt_text)
                span.tokens_used = span.prompt_tokens + span.completion_tokens
            span.finish(output={"content_length": len(accumulated)})

        except Exception as e:
            span.finish(error=str(e))
            yield AgentEvent(type="error", data={"message": str(e)})
            self.trace.finish()
            yield AgentEvent(type="trace", data=self.trace.to_dict())
            return

        self.trace.finish()
        yield AgentEvent(type="token_usage", data={
            "completion_tokens": self.trace.total_completion_tokens,
        })
        yield AgentEvent(type="done", data={"content": accumulated})
        yield AgentEvent(type="trace", data=self.trace.to_dict())
