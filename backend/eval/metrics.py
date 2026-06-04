"""RAG 检索评测指标"""
import math
from typing import List, Set
from dataclasses import dataclass


@dataclass
class QueryResult:
    query_id: int
    retrieved_doc_ids: List[str]
    relevant_doc_ids: Set[str]


def hit_rate_at_k(results: List[QueryResult], k: int) -> float:
    hits = 0
    for r in results:
        top_k = set(r.retrieved_doc_ids[:k])
        if top_k & r.relevant_doc_ids:
            hits += 1
    return hits / len(results) if results else 0.0


def recall_at_k(results: List[QueryResult], k: int) -> float:
    total_recall = 0.0
    for r in results:
        top_k = set(r.retrieved_doc_ids[:k])
        if r.relevant_doc_ids:
            total_recall += len(top_k & r.relevant_doc_ids) / len(r.relevant_doc_ids)
    return total_recall / len(results) if results else 0.0


def mrr_at_k(results: List[QueryResult], k: int) -> float:
    total_rr = 0.0
    for r in results:
        for rank, doc_id in enumerate(r.retrieved_doc_ids[:k], start=1):
            if doc_id in r.relevant_doc_ids:
                total_rr += 1.0 / rank
                break
    return total_rr / len(results) if results else 0.0


def ndcg_at_k(results: List[QueryResult], k: int) -> float:
    """
    Normalized Discounted Cumulative Gain @ K.
    Binary relevance: 1 if doc is in relevant set, 0 otherwise.
    """
    total_ndcg = 0.0
    valid = 0
    for r in results:
        if not r.relevant_doc_ids:
            continue
        valid += 1
        dcg = 0.0
        for rank, doc_id in enumerate(r.retrieved_doc_ids[:k], start=1):
            if doc_id in r.relevant_doc_ids:
                dcg += 1.0 / math.log2(rank + 1)
        ideal_hits = min(len(r.relevant_doc_ids), k)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
        total_ndcg += dcg / idcg if idcg > 0 else 0.0
    return total_ndcg / valid if valid else 0.0
