"""
对话记忆管理

基于 token 计数的滑动窗口 + 自动摘要压缩策略，
在有限 context 下维持长轮次连贯对话。
"""
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

try:
    import tiktoken
    _ENCODER = tiktoken.get_encoding("cl100k_base")
except ImportError:
    _ENCODER = None
    logger.warning("tiktoken 未安装，将使用字符估算 token 数")


def count_tokens(text: str) -> int:
    if _ENCODER:
        return len(_ENCODER.encode(text))
    return len(text) // 2


def count_messages_tokens(messages: List[Dict[str, str]]) -> int:
    total = 0
    for msg in messages:
        total += 4  # role + content overhead
        total += count_tokens(msg.get("content", ""))
    return total


async def summarize_messages(
    messages: List[Dict[str, str]],
    llm_client: Any,
) -> str:
    """用 LLM 压缩历史消息为摘要"""
    from llama_index.core.llms import ChatMessage
    conversation_text = "\n".join(
        f"{msg['role']}: {msg['content'][:300]}" for msg in messages
    )
    summary_prompt = [
        ChatMessage(
            role="system",
            content="你是对话摘要助手。请将以下对话历史压缩为一段简洁的摘要，保留关键信息、用户意图和重要结论。摘要应不超过 200 字。"
        ),
        ChatMessage(role="user", content=f"请总结以下对话：\n\n{conversation_text}")
    ]
    try:
        response = await llm_client.chat(summary_prompt)
        if hasattr(response, 'message') and hasattr(response.message, 'content'):
            return response.message.content
        return str(response)
    except Exception as e:
        logger.warning(f"摘要生成失败: {e}，使用简单截断")
        return f"[对话摘要] 之前讨论了 {len(messages)} 轮对话，主要话题包括相关问题的讨论。"


class ConversationMemory:
    """对话记忆管理器"""

    def __init__(self, max_tokens: int = 3500, reserve_tokens: int = 500):
        self.max_tokens = max_tokens
        self.reserve_tokens = reserve_tokens

    async def compress(
        self,
        messages: List[Dict[str, str]],
        llm_client: Optional[Any] = None,
    ) -> List[Dict[str, str]]:
        """智能压缩消息列表，确保不超过 token 预算"""
        if not messages:
            return []

        total = count_messages_tokens(messages)
        budget = self.max_tokens - self.reserve_tokens

        if total <= budget:
            return messages

        # 策略 1: 保留最近的消息，对早期消息生成摘要
        recent_count = min(6, len(messages))
        recent = messages[-recent_count:]
        recent_tokens = count_messages_tokens(recent)

        if recent_tokens >= budget:
            # 消息太长，只保留最近几条
            for n in range(recent_count, 0, -1):
                subset = messages[-n:]
                if count_messages_tokens(subset) <= budget:
                    return subset
            return messages[-2:]

        older = messages[:-recent_count]
        if not older:
            return recent

        # 策略 2: 用 LLM 生成摘要
        if llm_client:
            try:
                summary = await summarize_messages(older, llm_client)
                summary_msg = {"role": "system", "content": f"[历史对话摘要]\n{summary}"}
                result = [summary_msg] + recent
                if count_messages_tokens(result) <= budget:
                    return result
            except Exception as e:
                logger.warning(f"LLM 摘要失败: {e}")

        # 策略 3: 简单截断
        summary_msg = {
            "role": "system",
            "content": f"[历史摘要] 之前进行了 {len(older)} 轮对话。"
        }
        return [summary_msg] + recent

    def get_token_stats(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        total = count_messages_tokens(messages)
        return {
            "total_tokens": total,
            "max_tokens": self.max_tokens,
            "usage_ratio": round(total / self.max_tokens, 2) if self.max_tokens else 0,
            "message_count": len(messages),
            "needs_compression": total > (self.max_tokens - self.reserve_tokens),
        }
