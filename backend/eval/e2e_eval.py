"""Layer 3：端到端回答质量评测 — LLM-as-Judge 四维评分"""
import asyncio
import json
from typing import List, Dict, Any
from openai import AsyncOpenAI


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

    prompt = (
        "你是一个 RAG 系统的评测专家。请评估以下回答的质量。\n\n"
        f"用户问题：{query}\n\n"
        f"系统回答：{answer[:800]}\n\n"
        f"系统引用的来源：\n{sources_text}\n\n"
        f"标准参考文档：\n{ground_truth[:500]}\n\n"
        "请按以下 4 个维度评分（每项 1-5 分）：\n"
        "1. faithfulness（忠实度）：回答是否忠于检索到的来源？\n"
        "2. completeness（完整性）：回答是否覆盖了问题的所有方面？\n"
        "3. citation_quality（引用质量）：引用标注是否准确？\n"
        "4. no_hallucination（无幻觉）：有没有编造信息？5=无幻觉,1=严重幻觉\n\n"
        '只输出 JSON，不要其他内容：\n'
        '{"faithfulness":分数,"completeness":分数,"citation_quality":分数,"no_hallucination":分数,"reasoning":"一句话理由"}'
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.0,
        )
        text = resp.choices[0].message.content.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {"error": "无法解析", "raw": text}
    except Exception as e:
        return {"error": str(e)}


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
            }

    valid = [s for s in all_scores if isinstance(s.get("no_hallucination"), (int, float))]
    hallucination_rate = sum(1 for s in valid if s["no_hallucination"] <= 2) / len(valid) if valid else 0

    return {
        "total_queries": total,
        "valid_scores": len(valid),
        "dimension_scores": summary,
        "hallucination_rate": round(hallucination_rate, 4),
        "detail": all_scores,
    }
