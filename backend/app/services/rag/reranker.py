"""
Reranker 重排序模块

粗排（向量+BM25 混合检索）追求召回率，返回 top-20 候选。
Reranker 精排追求精度，从 top-20 中精选 top-5 给 LLM。

实现方式：LLM-based Reranking（使用现有 LLM API 做交叉评分），
无需额外部署 Cross-Encoder 模型，利用 LLM 的语义理解能力精排。
"""
import asyncio
import json
from typing import List, Tuple
from openai import AsyncOpenAI
from app.config import settings
from app.utils.logger_config import get_logger

logger = get_logger(__name__)

_rerank_client: AsyncOpenAI = None


def _get_rerank_client() -> AsyncOpenAI:
    global _rerank_client
    if _rerank_client is None:
        _rerank_client = AsyncOpenAI(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
        )
    return _rerank_client


async def rerank(
    query: str,
    candidates: List["RetrievalResult"],
    top_k: int = 5,
    model: str = "qwen-plus",
) -> List["RetrievalResult"]:
    """
    LLM-based Reranker：对粗排结果精排。

    原理：把 query 和每个候选 chunk 拼在一起让 LLM 评分（1-10），
    按分数重排后取 top_k。等价于 Cross-Encoder 的思路，
    但用 LLM 替代了专用重排模型。

    Args:
        query: 用户查询
        candidates: 粗排返回的候选结果列表
        top_k: 精排后返回的数量
        model: 用于重排的 LLM 模型

    Returns:
        重排后的 top_k 结果列表
    """
    from app.services.rag.retrieval import RetrievalResult

    if len(candidates) <= top_k:
        return candidates

    client = _get_rerank_client()

    # 构建批量评分 prompt — 一次 LLM 调用完成所有候选的评分
    # 根据候选数量动态调整截断长度，保证 LLM 能看到足够内容
    max_chars_per_doc = max(200, 4000 // len(candidates))
    docs_text = ""
    for i, c in enumerate(candidates):
        content_preview = c.content[:max_chars_per_doc].replace('\n', ' ')
        docs_text += f"[文档{i+1}] {content_preview}\n"

    prompt = (
        f"用户问题：{query}\n\n"
        f"以下是 {len(candidates)} 个候选文档片段，请评估每个片段与问题的相关程度。\n\n"
        f"{docs_text}\n"
        f"请为每个文档评分（1-10 分，10 分=完全相关，1 分=完全无关）。\n"
        f"只输出 JSON 数组，格式：[分数1, 分数2, ...]，不要其他内容。"
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.0,
        )
        text = resp.choices[0].message.content.strip()

        # 解析分数数组
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            scores = json.loads(text[start:end])
        else:
            logger.warning(f"Reranker 输出格式异常: {text[:100]}")
            return candidates[:top_k]

        if len(scores) != len(candidates):
            logger.warning(f"Reranker 分数数量不匹配: 期望 {len(candidates)}, 得到 {len(scores)}")
            return candidates[:top_k]

        # 按分数重排
        scored = list(zip(scores, candidates))
        scored.sort(key=lambda x: x[0], reverse=True)

        reranked = []
        for score, result in scored[:top_k]:
            result.rerank_score = float(score)
            result.retrieval_method = "hybrid+rerank"
            reranked.append(result)

        logger.info(
            f"Reranker 完成: {len(candidates)} 候选 → top-{top_k}, "
            f"最高分={scored[0][0]}, 最低入选分={scored[min(top_k-1, len(scored)-1)][0]}"
        )
        return reranked

    except Exception as e:
        logger.error(f"Reranker 失败，降级为粗排结果: {e}")
        return candidates[:top_k]
