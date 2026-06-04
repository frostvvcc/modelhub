"""
消融实验运行脚本 v2

对比三组配置的 Retrieval 指标：
  A. 纯向量检索
  B. 混合检索（Vector + BM25 + RRF）
  C. 混合检索 + Rerank

评测策略：用 source_content_preview 做**内容匹配**（而非 chunk_id 精确匹配），
解决数据集和索引不完全对齐的问题。
"""
import asyncio
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(".env")

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")


def _content_match(retrieved_content: str, reference_preview: str, threshold: int = 30) -> bool:
    """内容匹配：检查检索到的文本是否包含参考文本的关键片段"""
    if not reference_preview or not retrieved_content:
        return False
    ref_clean = reference_preview.replace("\n", "").replace(" ", "")[:200]
    ret_clean = retrieved_content.replace("\n", "").replace(" ", "")
    for start in range(0, min(len(ref_clean), 100), threshold):
        segment = ref_clean[start:start + threshold]
        if segment and segment in ret_clean:
            return True
    return False


async def run_experiment(config_name, vector_db_id, dataset, query_fn):
    results = []
    for item in dataset["items"]:
        query = item["query"]
        ref_preview = item.get("source_content_preview", "")
        ref_source = item.get("source_name", "")

        try:
            retrieved = await query_fn(vector_db_id, query)
        except Exception as e:
            print(f"  ❌ {query[:30]}... 失败: {e}")
            results.append({"query": query, "error": str(e)})
            continue

        hits = []
        for rank, r in enumerate(retrieved[:10]):
            is_hit = (
                _content_match(r.content, ref_preview)
                or (ref_source and ref_source in (r.source or ""))
            )
            hits.append(is_hit)

        results.append({
            "query": query,
            "hits": hits,
            "top_scores": [r.similarity for r in retrieved[:5]],
            "avg_score": sum(r.similarity for r in retrieved[:5]) / max(len(retrieved[:5]), 1),
        })

    return results


def calc_metrics(results, k_values=[3, 5]):
    metrics = {}
    valid = [r for r in results if "error" not in r]
    if not valid:
        return {"error": "no valid results"}

    for k in k_values:
        hits_count = 0
        mrrs = []

        for r in valid:
            hits = r["hits"][:k]
            hit = 1 if any(hits) else 0
            hits_count += hit

            rr = 0.0
            for rank, is_hit in enumerate(hits, 1):
                if is_hit:
                    rr = 1.0 / rank
                    break
            mrrs.append(rr)

        n = len(valid)
        metrics[f"hit_rate@{k}"] = round(hits_count / n, 4)
        metrics[f"mrr@{k}"] = round(sum(mrrs) / n, 4)

    avg_scores = [r["avg_score"] for r in valid]
    metrics["avg_similarity"] = round(sum(avg_scores) / len(avg_scores), 4) if avg_scores else 0
    metrics["valid_queries"] = len(valid)
    return metrics


async def main():
    from app.services.rag.retrieval import VectorRetriever

    dataset_path = os.path.join(os.path.dirname(__file__), "dataset.json")
    with open(dataset_path, encoding="utf-8") as f:
        dataset = json.load(f)

    vector_db_id = dataset.get("vector_db_id", 11)
    print(f"\n{'='*60}")
    print(f"消融实验 v2 (内容匹配): vector_db_id={vector_db_id}, {len(dataset['items'])} queries")
    print(f"{'='*60}\n")

    configs = [
        ("A: 纯向量", "🔵",
         lambda vdb, q: VectorRetriever.query(vdb, q, n_results=10)),
        ("B: 混合检索 (RRF α=0.7)", "🟢",
         lambda vdb, q: VectorRetriever.hybrid_query(vdb, q, n_results=10, alpha=0.7)),
        ("C: 混合检索 (RRF α=0.5)", "🟡",
         lambda vdb, q: VectorRetriever.hybrid_query(vdb, q, n_results=10, alpha=0.5)),
        ("D: Enhanced (Rewrite+Hybrid+Rerank)", "🔴",
         lambda vdb, q: VectorRetriever.enhanced_query(
             vdb, q, n_results=5, use_rewrite=True, use_rerank=True, use_hyde=False, use_graph=False)),
    ]

    all_metrics = {}
    for name, icon, query_fn in configs:
        print(f"{icon} {name}")
        t0 = time.time()
        results = await run_experiment(name, vector_db_id, dataset, query_fn)
        metrics = calc_metrics(results)
        elapsed = time.time() - t0
        metrics["latency_s"] = round(elapsed, 1)
        all_metrics[name] = metrics

        for k, v in metrics.items():
            print(f"   {k}: {v}")
        print()

    # Summary table
    print(f"{'='*72}")
    print("消融实验汇总")
    print(f"{'='*72}")
    header = f"{'指标':<20}"
    for name, _, _ in configs:
        short = name.split(":")[0] + name.split(":")[1][:6]
        header += f" {short:>12}"
    print(header)
    print("-" * 72)

    for metric_key in ["hit_rate@3", "hit_rate@5", "mrr@3", "mrr@5", "avg_similarity", "latency_s"]:
        row = f"{metric_key:<20}"
        for name, _, _ in configs:
            v = all_metrics[name].get(metric_key, "-")
            row += f" {v:>12}"
        print(row)

    # Key deltas
    if "A: 纯向量" in all_metrics and "B: 混合检索 (RRF α=0.7)" in all_metrics:
        a = all_metrics["A: 纯向量"]
        b = all_metrics["B: 混合检索 (RRF α=0.7)"]
        if isinstance(a.get("hit_rate@5"), (int, float)) and isinstance(b.get("hit_rate@5"), (int, float)):
            d = b["hit_rate@5"] - a["hit_rate@5"]
            print(f"\n🔑 混合检索 vs 纯向量 Hit Rate@5 变化: {d:+.4f}")
    if "B: 混合检索 (RRF α=0.7)" in all_metrics and "D: Enhanced (Rewrite+Hybrid+Rerank)" in all_metrics:
        b = all_metrics["B: 混合检索 (RRF α=0.7)"]
        d_metrics = all_metrics["D: Enhanced (Rewrite+Hybrid+Rerank)"]
        if isinstance(b.get("mrr@5"), (int, float)) and isinstance(d_metrics.get("mrr@5"), (int, float)):
            d = d_metrics["mrr@5"] - b["mrr@5"]
            print(f"🔑 Enhanced vs 混合检索 MRR@5 变化: {d:+.4f}")

    report = {
        "vector_db_id": vector_db_id,
        "total_queries": len(dataset["items"]),
        "eval_method": "content_match",
        "groups": all_metrics,
    }
    report_path = os.path.join(os.path.dirname(__file__), "ablation_report_live.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
