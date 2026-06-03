"""RAG 检索评测引擎 — 直接调用 VectorRetriever"""
import asyncio
import json
from typing import List, Dict
from eval.metrics import QueryResult, hit_rate_at_k, recall_at_k, mrr_at_k


async def evaluate_retrieval(
    dataset_path: str,
    alpha: float = 0.7,
    n_results: int = 5,
    rrf_k: int = 60,
) -> Dict:
    from app.services.rag.retrieval import VectorRetriever

    with open(dataset_path, encoding="utf-8") as f:
        dataset = json.load(f)

    vector_db_id = dataset["vector_db_id"]
    query_results: List[QueryResult] = []

    for item in dataset["items"]:
        try:
            results = await VectorRetriever.hybrid_query(
                vector_db_id=vector_db_id,
                query_text=item["query"],
                n_results=n_results,
                alpha=alpha,
            )
            retrieved_ids = [r.document_id for r in results]
        except Exception as e:
            print(f"  检索失败 (query_id={item['id']}): {e}")
            retrieved_ids = []

        query_results.append(QueryResult(
            query_id=item["id"],
            retrieved_doc_ids=retrieved_ids,
            relevant_doc_ids=set(item["relevant_document_ids"]),
        ))

    return {
        "params": {"alpha": alpha, "n_results": n_results, "rrf_k": rrf_k},
        "hit_rate@3": round(hit_rate_at_k(query_results, 3), 4),
        "hit_rate@5": round(hit_rate_at_k(query_results, 5), 4),
        "hit_rate@10": round(hit_rate_at_k(query_results, 10), 4),
        "recall@3": round(recall_at_k(query_results, 3), 4),
        "recall@5": round(recall_at_k(query_results, 5), 4),
        "recall@10": round(recall_at_k(query_results, 10), 4),
        "mrr@5": round(mrr_at_k(query_results, 5), 4),
        "mrr@10": round(mrr_at_k(query_results, 10), 4),
        "total_queries": len(query_results),
    }
