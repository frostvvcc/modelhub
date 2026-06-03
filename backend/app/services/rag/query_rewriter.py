"""
Query 改写模块

解决用户口语化提问和知识库书面用词不匹配的问题。

两种策略：
1. Multi-Query Rewriting：一个问题改写成多个检索 query，多路召回后合并
2. HyDE（Hypothetical Document Embedding）：让 LLM 生成假设答案，用答案文本去检索
"""
import asyncio
import json
from typing import List, Dict, Optional
from openai import AsyncOpenAI
from app.config import settings
from app.utils.logger_config import get_logger

logger = get_logger(__name__)

_rewrite_client: AsyncOpenAI = None


def _get_rewrite_client() -> AsyncOpenAI:
    global _rewrite_client
    if _rewrite_client is None:
        _rewrite_client = AsyncOpenAI(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
        )
    return _rewrite_client


async def rewrite_query(
    query: str,
    n_rewrites: int = 3,
    model: str = "qwen-plus",
) -> List[str]:
    """
    Multi-Query Rewriting：将用户的口语化问题改写为多个检索友好的 query。

    原理：用户说"毕设查重怎么弄"，知识库里写的是"毕业设计论文查重检测通知"。
    LLM 改写成多个角度的 query，每个 query 用不同的措辞检索，
    多路召回合并后覆盖面更广。

    Args:
        query: 用户原始问题
        n_rewrites: 生成的改写 query 数量
        model: 用于改写的 LLM 模型

    Returns:
        改写后的 query 列表（包含原始 query）
    """
    client = _get_rewrite_client()

    prompt = (
        f"你是一个搜索查询优化器。用户提了一个问题，请将它改写成 {n_rewrites} 个不同角度的检索查询，"
        f"用于在大学知识库中搜索相关文档。\n\n"
        f"要求：\n"
        f"1. 每个改写使用不同的关键词和表述方式\n"
        f"2. 覆盖问题可能涉及的不同方面\n"
        f"3. 使用正式、书面的措辞（知识库文档是官方通知）\n"
        f"4. 只输出 JSON 数组，格式：[\"query1\", \"query2\", \"query3\"]\n\n"
        f"用户问题：{query}"
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7,
        )
        text = resp.choices[0].message.content.strip()

        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            rewrites = json.loads(text[start:end])
            rewrites = [q.strip() for q in rewrites if isinstance(q, str) and q.strip()]
        else:
            logger.warning(f"Query 改写输出格式异常: {text[:100]}")
            return [query]

        # 原始 query 始终保留在第一位
        all_queries = [query] + [q for q in rewrites if q != query]
        logger.info(f"Query 改写: '{query[:30]}...' → {len(all_queries)} 个 query")
        return all_queries

    except Exception as e:
        logger.error(f"Query 改写失败，使用原始 query: {e}")
        return [query]


async def condense_follow_up(
    current_question: str,
    chat_history: List[Dict[str, str]],
    model: str = "qwen-plus",
) -> str:
    """
    Multi-turn Query Reformulation：结合对话历史，将追问补全为独立的检索查询。

    解决问题：用户追问"截止日期呢？"时，RAG 检索不知道在问什么的截止日期。
    本函数将追问 + 上下文合并成一个脱离对话也能理解的独立查询。

    示例：
        历史: "毕设查重流程是什么？" → "查重需要登录系统提交..."
        追问: "截止日期呢？"
        输出: "毕业设计论文查重的截止日期是什么时候？"

    Args:
        current_question: 用户当前追问
        chat_history: 之前的对话消息列表（正序），每条 {"role": "user"|"assistant", "content": "..."}
        model: 用于改写的 LLM 模型

    Returns:
        补全后的独立查询（如果改写失败则返回原始问题）
    """
    if not chat_history:
        return current_question

    client = _get_rewrite_client()

    history_text = ""
    for msg in chat_history[-6:]:
        role = "用户" if msg.get("role") == "user" else "助手"
        content = (msg.get("content") or "")[:300]
        history_text += f"{role}: {content}\n"

    prompt = (
        "你是一个查询改写器。根据对话历史，将用户的最新追问改写成一个独立的、完整的检索查询。\n\n"
        "规则：\n"
        "1. 改写后的查询必须脱离对话上下文也能被理解\n"
        "2. 保留用户追问的核心意图\n"
        "3. 使用正式、书面的措辞\n"
        "4. 如果追问本身已经是一个完整的独立问题，直接原样输出即可\n"
        "5. 只输出改写后的查询文本，不要任何解释\n\n"
        f"对话历史：\n{history_text}\n"
        f"用户追问：{current_question}\n\n"
        "改写后的独立查询："
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.0,
        )
        condensed = resp.choices[0].message.content.strip()
        condensed = condensed.strip('"').strip('“').strip('”')
        if condensed:
            logger.info(f"Query 补全: '{current_question[:30]}' → '{condensed[:50]}'")
            return condensed
        return current_question

    except Exception as e:
        logger.error(f"Query 补全失败，使用原始问题: {e}")
        return current_question


async def hyde_rewrite(
    query: str,
    model: str = "qwen-plus",
) -> str:
    """
    HyDE (Hypothetical Document Embedding)：
    让 LLM 生成一段"假设的理想答案"，然后用这段文本的 embedding 去检索。

    原理：用户的问题 embedding 和文档 embedding 可能在向量空间中距离较远，
    但 LLM 生成的"假设答案"在措辞上会更接近知识库文档的风格，
    从而在向量空间中更容易匹配到正确的文档。

    Args:
        query: 用户原始问题
        model: 用于生成假设答案的 LLM 模型

    Returns:
        假设的答案文本（用于替代原始 query 做向量检索）
    """
    client = _get_rewrite_client()

    prompt = (
        "请针对以下问题，写一段简短的回答（100-200字），"
        "假设你是大学教务处的工作人员，用正式的通知文体回答。\n"
        "不需要完全准确，只需要风格和用词接近大学官方文档即可。\n\n"
        f"问题：{query}\n\n回答："
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=250,
            temperature=0.5,
        )
        hyde_text = resp.choices[0].message.content.strip()
        logger.info(f"HyDE 生成: '{query[:30]}...' → {len(hyde_text)} 字符的假设文档")
        return hyde_text

    except Exception as e:
        logger.error(f"HyDE 生成失败，使用原始 query: {e}")
        return query
