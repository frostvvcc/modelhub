"""GraphRAG A/B 对比评测 — 有/无知识图谱上下文对回答质量的影响"""
import asyncio
import json
from typing import Dict, List
from openai import AsyncOpenAI
from eval.e2e_eval import judge_answer


async def run_graphrag_ab(
    dataset_path: str,
    vector_db_id: int,
    api_key: str,
    base_url: str,
    model: str = "qwen-plus",
    alpha: float = 0.7,
    n_results: int = 5,
    sample_size: int = 20,
) -> Dict:
    """对比 GraphRAG 开/关对回答质量的影响"""
    from app.services.rag.retrieval import VectorRetriever

    with open(dataset_path, encoding="utf-8") as f:
        dataset = json.load(f)

    items = dataset["items"][:sample_size]
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    results_with = []
    results_without = []

    for i, item in enumerate(items):
        query = item["query"]
        print(f"  [{i+1}/{len(items)}] {query[:40]}...")

        try:
            rag_results = await VectorRetriever.hybrid_query(
                vector_db_id=vector_db_id,
                query_text=query,
                n_results=n_results,
                alpha=alpha,
            )
            sources = [{"content": r.content, "source": r.source, "similarity": r.similarity} for r in rag_results]
            base_context = "\n\n".join(r.content[:300] for r in rag_results[:3])
        except Exception as e:
            print(f"    检索失败: {e}")
            continue

        graph_context = ""
        try:
            from app.services.rag.graph_rag import graph_augmented_context
            graph_context = await graph_augmented_context(query, vector_db_id) or ""
        except Exception as e:
            print(f"    GraphRAG 查询失败: {e}")

        with_graph_ctx = (base_context + "\n\n" + graph_context) if graph_context else base_context
        for label, context in [("without_graph", base_context), ("with_graph", with_graph_ctx)]:
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": f"基于以下参考资料回答问题，引用时标注[来源N]。\n\n参考资料：\n{context}"},
                        {"role": "user", "content": query},
                    ],
                    max_tokens=500,
                    temperature=0.3,
                )
                answer = resp.choices[0].message.content

                scores = await judge_answer(
                    client=client, model=model, query=query,
                    answer=answer, sources=sources,
                    ground_truth=item.get("source_content_preview", ""),
                )
                scores["query"] = query
                scores["has_graph_context"] = (label == "with_graph")
                scores["graph_triples_count"] = len(graph_context.split("\n")) if graph_context else 0

                if label == "with_graph":
                    results_with.append(scores)
                else:
                    results_without.append(scores)
            except Exception as e:
                print(f"    {label} 生成/评测失败: {e}")

        await asyncio.sleep(0.5)

    dims = ["faithfulness", "completeness", "citation_quality", "no_hallucination"]

    def avg_dim(items, dim):
        vals = [s[dim] for s in items if isinstance(s.get(dim), (int, float))]
        return round(sum(vals) / len(vals), 2) if vals else 0

    comparison = {}
    for dim in dims:
        w = avg_dim(results_with, dim)
        wo = avg_dim(results_without, dim)
        comparison[dim] = {
            "with_graph": w,
            "without_graph": wo,
            "delta": round(w - wo, 2),
        }

    return {
        "sample_size": len(items),
        "valid_with": len(results_with),
        "valid_without": len(results_without),
        "comparison": comparison,
        "conclusion": _summarize(comparison),
        "detail_with": results_with,
        "detail_without": results_without,
    }


def _summarize(comparison: Dict) -> str:
    improved = [d for d, v in comparison.items() if v["delta"] > 0.2]
    degraded = [d for d, v in comparison.items() if v["delta"] < -0.2]
    if improved and not degraded:
        return f"GraphRAG 在 {', '.join(improved)} 维度有明显提升"
    if degraded and not improved:
        return f"GraphRAG 在 {', '.join(degraded)} 维度有退化（可能引入噪声）"
    if not improved and not degraded:
        return "GraphRAG 对回答质量无显著影响（delta < 0.2）"
    return f"GraphRAG 提升了 {', '.join(improved)}，但退化了 {', '.join(degraded)}"
