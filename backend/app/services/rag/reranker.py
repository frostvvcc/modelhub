"""
Reranker 重排序模块

三级重排架构：
  Level 1: RRF 粗排（在 retrieval.py 中完成）
  Level 2: Cross-Encoder 精排（主选，本地推理，看完整内容）
  Level 3: LLM Listwise 精排（备用，API 调用）

Cross-Encoder 用 bge-reranker-v2-m3（多语言，MTEB 高排名），
模型在首次调用时加载并缓存为单例。
"""
import os
import asyncio
import json
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

RAG_RERANK_MODE = os.getenv("RAG_RERANK_MODE", "cross_encoder")  # cross_encoder | llm | off

_cross_encoder = None
_ce_lock = asyncio.Lock()
_llm_client = None


async def _get_cross_encoder(model_name: str = None):
    """单例加载 Cross-Encoder 模型（首次 ~2s，之后 0ms）"""
    global _cross_encoder
    if _cross_encoder is not None:
        return _cross_encoder

    async with _ce_lock:
        if _cross_encoder is not None:
            return _cross_encoder
        model_name = model_name or os.getenv("RAG_RERANK_CE_MODEL", "BAAI/bge-reranker-v2-m3")
        try:
            from sentence_transformers import CrossEncoder
            _cross_encoder = await asyncio.to_thread(CrossEncoder, model_name)
            logger.info(f"Cross-Encoder 加载完成: {model_name}")
        except ImportError:
            logger.warning("sentence-transformers 未安装，Cross-Encoder 不可用")
        except Exception as e:
            logger.warning(f"Cross-Encoder 加载失败: {e}")
    return _cross_encoder


def _get_llm_client():
    global _llm_client
    if _llm_client is None:
        from openai import AsyncOpenAI
        from app.config import settings
        _llm_client = AsyncOpenAI(
            api_key=getattr(settings, 'rag_llm_api_key', None) or settings.embedding_api_key,
            base_url=getattr(settings, 'rag_llm_base_url', None) or settings.embedding_base_url,
        )
    return _llm_client


async def cross_encoder_rerank(
    query: str,
    candidates: list,
    top_k: int = 5,
) -> list:
    """
    Cross-Encoder 精排：query 和 doc 在同一个 Transformer 里做交叉注意力。
    看完整 chunk 内容，不截断。精度高于 LLM-based，延迟 ~100ms。
    """
    model = await _get_cross_encoder()
    if model is None:
        logger.info("Cross-Encoder 不可用，降级为 LLM rerank")
        return await llm_rerank(query, candidates, top_k)

    pairs = [(query, c.content) for c in candidates]
    scores = await asyncio.to_thread(model.predict, pairs)

    scored = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
    reranked = []
    for score, result in scored[:top_k]:
        result.rerank_score = float(score)
        result.retrieval_method = "hybrid+cross_encoder"
        reranked.append(result)

    logger.info(
        f"Cross-Encoder rerank: {len(candidates)} → {len(reranked)}, "
        f"top={scored[0][0]:.4f}, cutoff={scored[min(top_k-1, len(scored)-1)][0]:.4f}"
    )
    return reranked


async def llm_rerank(
    query: str,
    candidates: list,
    top_k: int = 5,
    model: str = None,
) -> list:
    """
    LLM Listwise 精排：把所有候选拼成 prompt 让 LLM 打分（1-10）。
    精度好但延迟高（~1s），作为 Cross-Encoder 不可用时的 fallback。
    """
    from app.config import settings
    model = model or getattr(settings, 'rag_llm_model', None) or "qwen-plus"

    if len(candidates) <= top_k:
        return candidates

    client = _get_llm_client()

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

        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            scores = json.loads(text[start:end])
        else:
            logger.warning(f"LLM Reranker 输出格式异常: {text[:100]}")
            return candidates[:top_k]

        if len(scores) != len(candidates):
            logger.warning(f"LLM Reranker 分数数量不匹配: 期望 {len(candidates)}, 得到 {len(scores)}")
            return candidates[:top_k]

        scored = list(zip(scores, candidates))
        scored.sort(key=lambda x: x[0], reverse=True)

        reranked = []
        for score, result in scored[:top_k]:
            result.rerank_score = float(score)
            result.retrieval_method = "hybrid+rerank"
            reranked.append(result)

        logger.info(
            f"LLM Reranker 完成: {len(candidates)} → {top_k}, "
            f"最高分={scored[0][0]}, 最低入选={scored[min(top_k-1, len(scored)-1)][0]}"
        )
        return reranked

    except Exception as e:
        logger.error(f"LLM Reranker 失败，降级为粗排: {e}")
        return candidates[:top_k]


async def rerank(
    query: str,
    candidates: list,
    top_k: int = 5,
) -> list:
    """统一入口：根据 RAG_RERANK_MODE 选择重排策略"""
    if len(candidates) <= top_k:
        return candidates

    if RAG_RERANK_MODE == "cross_encoder":
        return await cross_encoder_rerank(query, candidates, top_k)
    elif RAG_RERANK_MODE == "llm":
        return await llm_rerank(query, candidates, top_k)
    else:
        return candidates[:top_k]
