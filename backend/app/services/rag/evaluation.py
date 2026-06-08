"""
RAG 评估模块 — 基于 RAGAS 框架的核心指标实现

提供四个维度的 RAG 质量评估：
  - Faithfulness:       回答是否忠实于检索到的上下文（幻觉检测）
  - Answer Relevancy:   回答是否切题（与原始问题的语义相关性）
  - Context Precision:  检索到的上下文中，排在前面的是否更相关（排序质量）
  - Context Recall:     参考答案中的关键信息是否被检索上下文覆盖

参考: Es et al., "RAGAS: Automated Evaluation of Retrieval Augmented Generation", 2023
"""
import json
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)

_eval_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _eval_client
    if _eval_client is None:
        import httpx
        _eval_client = AsyncOpenAI(
            api_key=settings.rag_llm_api_key or settings.embedding_api_key,
            base_url=settings.rag_llm_base_url or settings.embedding_base_url,
            timeout=httpx.Timeout(timeout=60.0, connect=10.0, read=50.0, write=10.0),
            max_retries=1,
        )
    return _eval_client


@dataclass
class RAGEvalResult:
    """单条评估结果"""
    faithfulness: float = 0.0
    answer_relevancy: float = 0.0
    context_precision: float = 0.0
    context_recall: float = 0.0
    overall_score: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "faithfulness": round(self.faithfulness, 4),
            "answer_relevancy": round(self.answer_relevancy, 4),
            "context_precision": round(self.context_precision, 4),
            "context_recall": round(self.context_recall, 4),
            "overall_score": round(self.overall_score, 4),
            "details": self.details,
        }


async def evaluate_faithfulness(
    answer: str,
    contexts: List[str],
    model: str = None,
) -> float:
    """
    Faithfulness: 回答中的每个声明是否都能从上下文中找到依据。
    score = supported_claims / total_claims
    """
    model = model or settings.rag_llm_model
    client = _get_client()

    if not answer or not contexts:
        return 1.0

    context_text = "\n\n".join(f"[上下文{i+1}] {c[:800]}" for i, c in enumerate(contexts[:10]))

    prompt = (
        "任务：评估回答的忠实度。判断回答中的每个事实声明是否被上下文支持。\n\n"
        f"上下文：\n{context_text}\n\n"
        f"回答：{answer[:2000]}\n\n"
        "步骤：\n"
        "1. 从回答中提取所有事实性声明\n"
        "2. 逐条判断是否被上下文支持\n"
        "3. 计算 supported / total\n\n"
        '输出 JSON：{"claims": [{"text": "...", "supported": true/false}], '
        '"supported_count": N, "total_count": N, "score": 0.0-1.0}'
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip()
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(raw[start:end])
            return float(result.get("score", 0.0))
    except Exception as e:
        logger.warning(f"Faithfulness 评估失败: {e}")
    return 0.0


async def evaluate_answer_relevancy(
    question: str,
    answer: str,
    model: str = None,
) -> float:
    """
    Answer Relevancy: 回答与问题的语义相关性。
    通过 LLM 从回答反向生成问题，比较与原始问题的一致性。
    """
    model = model or settings.rag_llm_model
    client = _get_client()

    if not question or not answer:
        return 0.0

    prompt = (
        "任务：评估回答与问题的相关性。\n\n"
        f"原始问题：{question}\n\n"
        f"回答：{answer[:2000]}\n\n"
        "评估标准：\n"
        "- 1.0: 回答完全针对问题，信息充分\n"
        "- 0.7-0.9: 回答基本切题，但有部分冗余或遗漏\n"
        "- 0.4-0.6: 回答部分相关，但偏离了问题核心\n"
        "- 0.1-0.3: 回答与问题关联度低\n"
        "- 0.0: 完全不相关\n\n"
        '输出 JSON：{"score": 0.0-1.0, "reason": "一句话理由"}'
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip()
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(raw[start:end])
            return float(result.get("score", 0.0))
    except Exception as e:
        logger.warning(f"Answer Relevancy 评估失败: {e}")
    return 0.0


async def evaluate_context_precision(
    question: str,
    contexts: List[str],
    model: str = None,
) -> float:
    """
    Context Precision: 检索结果的排序质量。
    衡量相关上下文是否排在前面（Precision@K 加权平均）。
    """
    model = model or settings.rag_llm_model
    client = _get_client()

    if not question or not contexts:
        return 0.0

    context_list = "\n".join(
        f"[{i+1}] {c[:300]}" for i, c in enumerate(contexts[:10])
    )

    prompt = (
        "任务：判断每个检索结果与问题的相关性。\n\n"
        f"问题：{question}\n\n"
        f"检索结果（按排序）：\n{context_list}\n\n"
        '对每个结果判断是否相关，输出 JSON 数组：[true/false, true/false, ...]'
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip()
        start, end = raw.find("["), raw.rfind("]") + 1
        if start >= 0 and end > start:
            relevance = json.loads(raw[start:end])
            # Precision@K 加权平均 (RAGAS 公式)
            if not relevance:
                return 0.0
            cumulative_precision = 0.0
            relevant_count = 0
            for k, is_relevant in enumerate(relevance):
                if is_relevant:
                    relevant_count += 1
                    precision_at_k = relevant_count / (k + 1)
                    cumulative_precision += precision_at_k
            return cumulative_precision / len(relevance) if relevance else 0.0
    except Exception as e:
        logger.warning(f"Context Precision 评估失败: {e}")
    return 0.0


async def evaluate_context_recall(
    question: str,
    answer: str,
    contexts: List[str],
    reference_answer: Optional[str] = None,
    model: str = None,
) -> float:
    """
    Context Recall: 参考答案（或 LLM 自身知识）中的关键信息点是否被检索上下文覆盖。
    如果没有 reference_answer，则从问题推断期望的关键信息点。
    """
    model = model or settings.rag_llm_model
    client = _get_client()

    if not contexts:
        return 0.0

    context_text = "\n\n".join(f"[上下文{i+1}] {c[:500]}" for i, c in enumerate(contexts[:10]))

    if reference_answer:
        ref_section = f"参考答案：{reference_answer[:1000]}"
    else:
        ref_section = f"问题：{question}\n回答：{answer[:1000]}"

    prompt = (
        "任务：评估检索上下文对回答关键信息的覆盖率。\n\n"
        f"{ref_section}\n\n"
        f"检索上下文：\n{context_text}\n\n"
        "步骤：\n"
        "1. 从回答中提取关键信息点\n"
        "2. 判断每个信息点是否能在检索上下文中找到\n"
        "3. 计算 covered / total\n\n"
        '输出 JSON：{"key_points": [{"point": "...", "covered": true/false}], '
        '"covered_count": N, "total_count": N, "score": 0.0-1.0}'
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip()
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(raw[start:end])
            return float(result.get("score", 0.0))
    except Exception as e:
        logger.warning(f"Context Recall 评估失败: {e}")
    return 0.0


async def evaluate_rag(
    question: str,
    answer: str,
    contexts: List[str],
    reference_answer: Optional[str] = None,
    model: str = None,
) -> RAGEvalResult:
    """
    完整 RAG 评估：并行计算四个 RAGAS 指标，返回综合评分。
    """
    import asyncio
    model = model or settings.rag_llm_model

    tasks = {
        "faithfulness": evaluate_faithfulness(answer, contexts, model),
        "answer_relevancy": evaluate_answer_relevancy(question, answer, model),
        "context_precision": evaluate_context_precision(question, contexts, model),
        "context_recall": evaluate_context_recall(question, answer, contexts, reference_answer, model),
    }

    keys = list(tasks.keys())
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    scores = {}
    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            logger.warning(f"评估指标 {key} 失败: {result}")
            scores[key] = 0.0
        else:
            scores[key] = float(result)

    overall = sum(scores.values()) / len(scores) if scores else 0.0

    eval_result = RAGEvalResult(
        faithfulness=scores.get("faithfulness", 0.0),
        answer_relevancy=scores.get("answer_relevancy", 0.0),
        context_precision=scores.get("context_precision", 0.0),
        context_recall=scores.get("context_recall", 0.0),
        overall_score=overall,
    )

    logger.info(
        f"[RAG 评估] faithfulness={eval_result.faithfulness:.2f}, "
        f"relevancy={eval_result.answer_relevancy:.2f}, "
        f"precision={eval_result.context_precision:.2f}, "
        f"recall={eval_result.context_recall:.2f}, "
        f"overall={eval_result.overall_score:.2f}"
    )

    return eval_result


@dataclass
class EvalDatasetItem:
    """评估数据集单条记录"""
    question: str
    contexts: List[str]
    answer: str
    reference_answer: Optional[str] = None


async def batch_evaluate(
    dataset: List[EvalDatasetItem],
    model: str = None,
    max_concurrency: int = 5,
) -> Dict[str, Any]:
    """
    批量评估：对评估数据集运行全量 RAGAS 指标，返回聚合统计。
    支持并发控制，避免 API 限流。
    """
    import asyncio
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _eval_one(item: EvalDatasetItem) -> RAGEvalResult:
        async with semaphore:
            return await evaluate_rag(
                item.question, item.answer, item.contexts,
                item.reference_answer, model,
            )

    results = await asyncio.gather(
        *[_eval_one(item) for item in dataset],
        return_exceptions=True,
    )

    valid_results = [r for r in results if isinstance(r, RAGEvalResult)]
    if not valid_results:
        return {"error": "所有评估均失败", "total": len(dataset), "succeeded": 0}

    n = len(valid_results)
    agg = {
        "total": len(dataset),
        "succeeded": n,
        "failed": len(dataset) - n,
        "avg_faithfulness": round(sum(r.faithfulness for r in valid_results) / n, 4),
        "avg_answer_relevancy": round(sum(r.answer_relevancy for r in valid_results) / n, 4),
        "avg_context_precision": round(sum(r.context_precision for r in valid_results) / n, 4),
        "avg_context_recall": round(sum(r.context_recall for r in valid_results) / n, 4),
        "avg_overall": round(sum(r.overall_score for r in valid_results) / n, 4),
        "per_item": [r.to_dict() for r in valid_results],
    }

    logger.info(
        f"[批量评估] {n}/{len(dataset)} 成功, "
        f"avg_overall={agg['avg_overall']:.2f}"
    )

    return agg
