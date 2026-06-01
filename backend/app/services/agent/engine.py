"""
ReAct Agent 引擎

基于 ReAct (Reasoning + Acting) 模式的多轮工具调用循环。
用户消息 → LLM 判断是否需要调用工具
  → 需要：解析 tool_call，执行工具，把结果喂回 LLM
  → 不需要：直接回复
  → 循环直到 LLM 给出最终回答（设最大轮次兜底）
"""
import json
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass

from app.services.agent.tools import BaseTool
from app.services.agent.state_machine import AgentStateMachine, AgentState
from app.services.agent.trace import TraceContext, Span
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


@dataclass
class AgentEvent:
    """Agent 运行过程中产生的事件，用于 SSE 流式推送"""
    type: str  # state_change | thinking | tool_call | tool_result | token | sources | trace | done | error
    data: Dict[str, Any]


class AgentEngine:
    """ReAct Agent 引擎"""

    def __init__(
        self,
        tools: List[BaseTool],
        max_iterations: int = 5,
        token_budget: int = 8000,
    ):
        self.tools = {tool.name: tool for tool in tools}
        self.tool_list = tools
        self.max_iterations = max_iterations
        self.token_budget = token_budget
        self.state_machine = AgentStateMachine()
        self.trace = TraceContext()

    def _get_openai_tools(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self.tool_list]

    async def run(
        self,
        messages: List[Dict[str, str]],
        llm_client: Any,
        system_messages: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        执行 ReAct 循环，yield AgentEvent 流。

        messages: 对话历史 (OpenAI 格式)
        llm_client: AsyncChatGLM 实例
        system_messages: 额外的系统消息（RAG prompt 等）
        """
        # IDLE → PLANNING
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

            # 调用 LLM
            llm_span = self.trace.create_span(
                f"llm_call_{iteration}", span_type="llm_call",
                input_data={"message_count": len(working_messages), "iteration": iteration},
            )

            try:
                client = llm_client._get_client()
                all_msgs = [{"role": "system", "content": llm_client.system_prompt}] + working_messages

                response = await client.chat.completions.create(
                    model=llm_client.model,
                    messages=all_msgs,
                    tools=openai_tools if openai_tools else None,
                    temperature=llm_client.temperature,
                    top_p=llm_client.top_p,
                )

                choice = response.choices[0]
                message = choice.message

                if response.usage:
                    llm_span.tokens_used = response.usage.total_tokens
                    llm_span.prompt_tokens = response.usage.prompt_tokens
                    llm_span.completion_tokens = response.usage.completion_tokens

                llm_span.finish(output={"finish_reason": choice.finish_reason})

            except Exception as e:
                llm_span.finish(error=str(e))
                self.state_machine.transition(AgentState.ERROR, f"LLM 调用失败: {e}")
                yield AgentEvent(type="error", data={"message": f"模型调用失败: {str(e)}"})
                self.trace.finish()
                yield AgentEvent(type="trace", data=self.trace.to_dict())
                return

            # 检查是否有 tool_calls
            if message.tool_calls:
                # PLANNING/REFLECTING → TOOL_CALLING
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

                # 将 assistant 消息（含 tool_calls）加入对话
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

                # 执行每个工具
                for tc in message.tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}

                    yield AgentEvent(type="tool_call", data={
                        "tool": tool_name,
                        "args": tool_args,
                        "call_id": tc.id,
                    })

                    # 执行工具
                    tool_span = self.trace.create_span(
                        f"tool:{tool_name}", span_type="tool_call",
                        input_data={"tool": tool_name, "args": tool_args},
                    )

                    tool = self.tools.get(tool_name)
                    if tool:
                        try:
                            result = await tool.execute(**tool_args)
                            # 缓存 RAG 结果以在最终回复中使用
                            if tool_name == "knowledge_search" and result.get("_raw_rag_result"):
                                rag_result_cache = result.pop("_raw_rag_result")
                            tool_span.finish(output=result)
                        except Exception as e:
                            result = {"error": str(e)}
                            tool_span.finish(error=str(e))
                    else:
                        result = {"error": f"未知工具: {tool_name}"}
                        tool_span.finish(error=f"未知工具: {tool_name}")

                    yield AgentEvent(type="tool_result", data={
                        "tool": tool_name,
                        "result": result,
                        "call_id": tc.id,
                        "latency_ms": tool_span.latency_ms,
                    })

                    # 将工具结果加入对话
                    working_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str)[:2000],
                    })

                # TOOL_CALLING → REFLECTING
                if self.state_machine.can_transition(AgentState.REFLECTING):
                    self.state_machine.transition(AgentState.REFLECTING, "分析工具返回结果")
                    yield AgentEvent(type="state_change", data={
                        "state": AgentState.REFLECTING.value,
                        "label": "分析工具结果中...",
                    })

                continue

            # 无 tool_calls → 最终回答
            # 流式输出 token
            if self.state_machine.can_transition(AgentState.RESPONDING):
                self.state_machine.transition(AgentState.RESPONDING, "生成最终回答")
                yield AgentEvent(type="state_change", data={
                    "state": AgentState.RESPONDING.value,
                    "label": "生成回答中...",
                })

            # 重新调用 LLM 进行流式输出
            try:
                stream_span = self.trace.create_span(
                    "stream_response", span_type="llm_stream",
                    input_data={"message_count": len(working_messages)},
                )

                stream = await client.chat.completions.create(
                    model=llm_client.model,
                    messages=all_msgs,
                    temperature=llm_client.temperature,
                    top_p=llm_client.top_p,
                    stream=True,
                )

                stream_tokens = 0
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        accumulated_content += delta.content
                        stream_tokens += 1
                        yield AgentEvent(type="token", data={"content": delta.content})

                stream_span.completion_tokens = stream_tokens
                stream_span.finish(output={"content_length": len(accumulated_content)})

            except Exception as e:
                # 回退到非流式结果
                accumulated_content = message.content or ""
                for i in range(0, len(accumulated_content), 4):
                    chunk = accumulated_content[i:i+4]
                    yield AgentEvent(type="token", data={"content": chunk})

            break

        # 如果超出最大轮次
        if iteration >= self.max_iterations and not accumulated_content:
            accumulated_content = "抱歉，经过多次尝试仍未能得到满意的结果，请尝试更具体的问题。"
            yield AgentEvent(type="token", data={"content": accumulated_content})

        # RESPONDING → DONE
        if self.state_machine.can_transition(AgentState.DONE):
            self.state_machine.transition(AgentState.DONE, "回答完成")

        self.trace.finish()

        yield AgentEvent(type="done", data={
            "content": accumulated_content,
            "iterations": iteration,
            "rag_result": rag_result_cache,
            "state_machine": self.state_machine.to_dict(),
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
            all_msgs = [{"role": "system", "content": llm_client.system_prompt}] + messages

            stream = await client.chat.completions.create(
                model=llm_client.model,
                messages=all_msgs,
                temperature=llm_client.temperature,
                top_p=llm_client.top_p,
                stream=True,
            )

            token_count = 0
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    accumulated += delta.content
                    token_count += 1
                    yield AgentEvent(type="token", data={"content": delta.content})

            span.completion_tokens = token_count
            span.finish(output={"content_length": len(accumulated)})

        except Exception as e:
            span.finish(error=str(e))
            yield AgentEvent(type="error", data={"message": str(e)})
            self.trace.finish()
            yield AgentEvent(type="trace", data=self.trace.to_dict())
            return

        self.trace.finish()
        yield AgentEvent(type="done", data={"content": accumulated})
        yield AgentEvent(type="trace", data=self.trace.to_dict())
