"""
Claim-Level Grounding 验证模块

LLM 回复后，将回答拆成独立的事实声明（claims），
逐条检查是否被检索到的 source 支撑（NLI 三分类：supported/unsupported/contradicted）。

用于替代简单的 avg_similarity 映射，实现真正的幻觉检测。
"""
import json
import logging
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)

_grounding_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _grounding_client
    if _grounding_client is None:
        import httpx
        _grounding_client = AsyncOpenAI(
            api_key=getattr(settings, 'rag_llm_api_key', None) or settings.embedding_api_key,
            base_url=getattr(settings, 'rag_llm_base_url', None) or settings.embedding_base_url,
            timeout=httpx.Timeout(timeout=60.0, connect=10.0, read=50.0, write=10.0),
            max_retries=1,
        )
    return _grounding_client


async def _extract_claims(answer: str, model: str) -> List[str]:
    """将 LLM 回答拆分成独立的事实声明"""
    client = _get_client()
    prompt = (
        "将以下回答拆分成独立的事实声明（claims），每条 claim 是一个可以独立验证真伪的陈述。\n"
        "去掉连接词、过渡语、主观评价，只保留客观事实。\n"
        '输出 JSON 数组：["claim1", "claim2", ...]\n\n'
        f"回答：{answer[:2000]}"
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip()
        start, end = raw.find("["), raw.rfind("]") + 1
        if start >= 0 and end > start:
            return [str(c).strip() for c in json.loads(raw[start:end]) if isinstance(c, str) and c.strip()]
    except Exception as e:
        logger.error(f"Claim 提取失败: {e}")
    return []


async def _verify_claims(
    claims: List[str],
    source_texts: str,
    model: str,
) -> List[Dict[str, Any]]:
    """NLI 三分类验证每条 claim 是否被 source 支撑"""
    client = _get_client()
    prompt = (
        "你是一个事实核查专家。对于每条声明（claim），判断它是否被以下来源文本支撑。\n\n"
        f"来源文本：\n{source_texts[:4000]}\n\n"
        "声明列表：\n"
        + "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims))
        + "\n\n"
        "对每条声明判断：\n"
        "- supported：来源文本明确支持该声明\n"
        "- unsupported：来源文本中找不到支持该声明的依据\n"
        "- contradicted：来源文本与该声明矛盾\n\n"
        '输出 JSON 数组：[{"claim": "...", "verdict": "supported|unsupported|contradicted", '
        '"source_idx": 来源编号或null, "reason": "一句话理由"}, ...]'
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip()
        logger.debug(f"NLI 原始返回: {raw[:500]}")
        start, end = raw.find("["), raw.rfind("]") + 1
        if start >= 0 and end > start:
            results = json.loads(raw[start:end])
            return [
                {
                    "text": r.get("claim", claims[i] if i < len(claims) else ""),
                    "supported": r.get("verdict") == "supported",
                    "verdict": r.get("verdict", "unknown"),
                    "source_idx": r.get("source_idx"),
                    "reason": r.get("reason", ""),
                }
                for i, r in enumerate(results[:len(claims)])
            ]
    except Exception as e:
        logger.error(f"Claim 验证失败: {e}", exc_info=True)

    # fail-open: 验证失败 ≠ 验证不通过，默认放行，避免误触发 CRAG
    return [{"text": c, "supported": True, "verdict": "unknown", "source_idx": None, "reason": "验证服务不可用，默认放行"} for c in claims]


async def verify_grounding(
    answer: str,
    sources: List[Dict[str, Any]],
    model: str = None,
) -> Dict[str, Any]:
    """
    完整的 Claim-Level Grounding 验证流程：
    1. 拆 claims → 2. NLI 验证 → 3. 统计 grounded ratio

    Returns:
        {
            "claims": [{"text": "...", "supported": True, "verdict": "supported", ...}, ...],
            "grounded_ratio": 0.85,
            "unsupported_claims": [{"text": "...", ...}, ...],
            "contradicted_claims": [{"text": "...", ...}, ...],
            "total_claims": 10,
            "supported_count": 8,
        }
    """
    model = model or settings.rag_llm_model

    if not answer or not sources:
        return {
            "claims": [], "grounded_ratio": 1.0,
            "unsupported_claims": [], "contradicted_claims": [],
            "total_claims": 0, "supported_count": 0,
        }

    claims = await _extract_claims(answer, model)
    if not claims:
        return {
            "claims": [], "grounded_ratio": 1.0,
            "unsupported_claims": [], "contradicted_claims": [],
            "total_claims": 0, "supported_count": 0,
        }

    source_texts = "\n\n".join(
        f"[来源{i+1}] {s.get('content', '')}"
        for i, s in enumerate(sources[:10])
    )

    verified = await _verify_claims(claims, source_texts, model)

    supported = [c for c in verified if c.get("supported")]
    unsupported = [c for c in verified if c.get("verdict") == "unsupported"]
    contradicted = [c for c in verified if c.get("verdict") == "contradicted"]
    ratio = len(supported) / len(verified) if verified else 1.0

    logger.info(
        f"Grounding 验证: {len(verified)} claims, "
        f"{len(supported)} supported, {len(unsupported)} unsupported, "
        f"{len(contradicted)} contradicted, ratio={ratio:.2%}"
    )

    return {
        "claims": verified,
        "grounded_ratio": round(ratio, 4),
        "unsupported_claims": unsupported,
        "contradicted_claims": contradicted,
        "total_claims": len(verified),
        "supported_count": len(supported),
    }
