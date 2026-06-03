"""RAG 检索评测指标"""
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
