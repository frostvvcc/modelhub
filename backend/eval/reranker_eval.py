"""Reranker 消融评测 — 对比 off / cross_encoder / llm 三种模式"""
import asyncio
import os
import json
from typing import Dict, List
from eval.metrics import QueryResult, hit_rate_at_k, recall_at_k, mrr_at_k, ndcg_at_k


async def evaluate_with_rerank_mode(
    dataset_path: str,
    mode: str,
    alpha: float = 0.7,
    n_results: int = 5,
) -> Dict:
    """用指定 rerank 模式跑一轮检索评测"""
    original_mode = os.environ.get("RAG_RERANK_MODE", "cross_encoder")
    os.environ["RAG_RERANK_MODE"] = mode

    try:
        import importlib
        import app.services.rag.reranker as reranker_mod
        reranker_mod.RAG_RERANK_MODE = mode
    except Exception:
        pass

    try:
        from app.services.rag.retrieval import VectorRetriever

        with open(dataset_path, encoding="utf-8") as f:
            dataset = json.load(f)

        vector_db_id = dataset["vector_db_id"]
        query_results: List[QueryResult] = []

        for item in dataset["items"]:
            try:
                results = await VectorRetriever.enhanced_query(
                    vector_db_id=vector_db_id,
                    query_text=item["query"],
                    n_results=n_results * 3,
                    alpha=alpha,
                    use_rewrite=False,
                    use_rerank=(mode != "off"),
                    use_hyde=False,
                )
                retrieved_ids = [r.document_id for r in results[:n_results]]
            except Exception as e:
                print(f"    检索失败 (query_id={item['id']}): {e}")
                retrieved_ids = []

            query_results.append(QueryResult(
                query_id=item["id"],
                retrieved_doc_ids=retrieved_ids,
                relevant_doc_ids=set(item["relevant_document_ids"]),
            ))

        return {
            "mode": mode,
            "hit_rate@5": round(hit_rate_at_k(query_results, 5), 4),
            "recall@5": round(recall_at_k(query_results, 5), 4),
            "mrr@5": round(mrr_at_k(query_results, 5), 4),
            "ndcg@5": round(ndcg_at_k(query_results, 5), 4),
            "total_queries": len(query_results),
        }
    finally:
        os.environ["RAG_RERANK_MODE"] = original_mode
        try:
            reranker_mod.RAG_RERANK_MODE = original_mode
        except Exception:
            pass


async def run_reranker_ablation(
    dataset_path: str,
    output_path: str,
) -> Dict:
    """跑三种 rerank 模式的消融"""
    modes = ["off", "llm", "cross_encoder"]
    results = []

    for mode in modes:
        print(f"\n  Reranker mode={mode} ...", end=" ", flush=True)
        try:
            metrics = await evaluate_with_rerank_mode(dataset_path, mode)
            results.append(metrics)
            print(
                f"Recall@5={metrics['recall@5']:.4f}  "
                f"MRR@5={metrics['mrr@5']:.4f}  "
                f"NDCG@5={metrics['ndcg@5']:.4f}"
            )
        except Exception as e:
            print(f"失败: {e}")
            results.append({"mode": mode, "error": str(e)})

        await asyncio.sleep(0.3)

    best = max(
        [r for r in results if "recall@5" in r],
        key=lambda r: r["recall@5"],
        default=None,
    )

    report = {
        "description": "Reranker 模式消融（off=不重排, llm=LLM精排, cross_encoder=CE精排）",
        "best_mode": best["mode"] if best else "unknown",
        "results": results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report
