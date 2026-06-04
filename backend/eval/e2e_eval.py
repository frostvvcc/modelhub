"""Layer 3：端到端回答质量评测 — LLM-as-Judge 四维评分"""
import asyncio
import json
import re
from typing import List, Dict, Any
from openai import AsyncOpenAI

MAX_JUDGE_RETRIES = 2

JUDGE_PROMPT = """\
你是一个 RAG 系统的评测专家。请评估以下回答的质量。

用户问题：{query}

系统回答：{answer}

系统引用的来源：
{sources_text}

标准参考文档：
{ground_truth}

请按以下 4 个维度评分（每项 1-5 分）：
1. faithfulness（忠实度）：回答是否忠于检索到的来源？
2. completeness（完整性）：回答是否覆盖了问题的所有方面？
3. citation_quality（引用质量）：引用标注是否准确？
4. no_hallucination（无幻觉）：有没有编造信息？5=无幻觉,1=严重幻觉

严格按如下 JSON 格式输出（不要输出其他任何内容）：
```json
{{"faithfulness": 分数, "completeness": 分数, "citation_quality": 分数, "no_hallucination": 分数, "reasoning": "简短理由"}}
```"""


def _extract_json(text: str) -> Dict:
    """多策略 JSON 提取：先找代码块，再找花括号，最后正则兜底。"""
    code_block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if code_block:
        return json.loads(code_block.group(1))

    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    pattern = r'"?(\w+)"?\s*[:：]\s*(\d)'
    matches = dict(re.findall(pattern, text))
    dims = ["faithfulness", "completeness", "citation_quality", "no_hallucination"]
    if all(d in matches for d in dims):
        return {d: int(matches[d]) for d in dims}

    raise ValueError(f"无法从 LLM 输出中提取评分 JSON")


async def judge_answer(
    client: AsyncOpenAI,
    model: str,
    query: str,
    answer: str,
    sources: List[Dict],
    ground_truth: str,
) -> Dict:
    sources_text = "\n".join(
        f"[来源{i+1}]: {s.get('content', '')[:200]}"
        for i, s in enumerate(sources[:5])
    )

    prompt = JUDGE_PROMPT.format(
        query=query,
        answer=answer[:800],
        sources_text=sources_text,
        ground_truth=ground_truth[:500],
    )

    text = ""
    for attempt in range(MAX_JUDGE_RETRIES + 1):
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.0,
            )
            text = resp.choices[0].message.content.strip()
            result = _extract_json(text)
            dims = ["faithfulness", "completeness", "citation_quality", "no_hallucination"]
            for d in dims:
                if d not in result or not isinstance(result[d], (int, float)):
                    raise ValueError(f"缺少维度 {d}")
                result[d] = max(1, min(5, int(result[d])))
            return result
        except Exception as e:
            if attempt < MAX_JUDGE_RETRIES:
                await asyncio.sleep(0.3)
                continue
            return {"error": f"解析失败(重试{MAX_JUDGE_RETRIES}次): {e}", "raw": text}


async def run_e2e_eval(
    dataset_path: str,
    vector_db_id: int,
    api_key: str,
    base_url: str,
    model: str = "qwen-plus",
    alpha: float = 0.7,
    n_results: int = 5,
) -> Dict:
    from app.services.rag.retrieval import VectorRetriever

    with open(dataset_path, encoding="utf-8") as f:
        dataset = json.load(f)

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    llm_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    all_scores = []
    total = len(dataset["items"])

    for i, item in enumerate(dataset["items"]):
        print(f"  [{i+1}/{total}] 评测: {item['query'][:40]}...", end=" ", flush=True)

        try:
            results = await VectorRetriever.hybrid_query(
                vector_db_id=vector_db_id,
                query_text=item["query"],
                n_results=n_results,
                alpha=alpha,
            )
            sources = [{"content": r.content, "source": r.source, "similarity": r.similarity} for r in results]
            context = "\n\n".join(r.content[:300] for r in results[:3])
        except Exception as e:
            print(f"检索失败: {e}")
            all_scores.append({"error": f"检索失败: {e}", "query": item["query"]})
            continue

        try:
            answer_resp = await llm_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": f"你是一个智能助手。基于以下参考资料回答问题，引用时标注[来源N]。\n\n参考资料：\n{context}"},
                    {"role": "user", "content": item["query"]},
                ],
                max_tokens=500,
                temperature=0.3,
            )
            answer = answer_resp.choices[0].message.content
        except Exception as e:
            print(f"生成失败: {e}")
            all_scores.append({"error": f"生成失败: {e}", "query": item["query"]})
            continue

        scores = await judge_answer(
            client=client,
            model=model,
            query=item["query"],
            answer=answer,
            sources=sources,
            ground_truth=item.get("source_content_preview", ""),
        )
        scores["query"] = item["query"]
        scores["answer_preview"] = answer[:200]
        all_scores.append(scores)

        f_score = scores.get("faithfulness", "?")
        h_score = scores.get("no_hallucination", "?")
        print(f"忠实度={f_score} 无幻觉={h_score}")

        await asyncio.sleep(0.5)

    dims = ["faithfulness", "completeness", "citation_quality", "no_hallucination"]
    summary = {}
    for dim in dims:
        values = [s[dim] for s in all_scores if isinstance(s.get(dim), (int, float))]
        if values:
            summary[dim] = {
                "avg": round(sum(values) / len(values), 2),
                "min": min(values),
                "max": max(values),
                "count": len(values),
            }

    valid = [s for s in all_scores if isinstance(s.get("no_hallucination"), (int, float))]
    parse_failures = [s for s in all_scores if "error" in s and "解析" in str(s.get("error", ""))]
    hallucination_rate = sum(1 for s in valid if s["no_hallucination"] <= 2) / len(valid) if valid else 0

    return {
        "total_queries": total,
        "valid_scores": len(valid),
        "parse_failures": len(parse_failures),
        "parse_success_rate": round(len(valid) / total, 4) if total else 0,
        "dimension_scores": summary,
        "hallucination_rate": round(hallucination_rate, 4),
        "detail": all_scores,
    }
