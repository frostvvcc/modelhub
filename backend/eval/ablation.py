"""消融实验 — 每次只变一个参数，观察独立影响 + Bootstrap 置信区间"""
import asyncio
import json
import random
from datetime import datetime
from typing import Dict, List, Any
from eval.runner import evaluate_retrieval
from eval.metrics import QueryResult, recall_at_k, mrr_at_k, ndcg_at_k

ABLATION_EXPERIMENTS = {
    "alpha": {
        "values": [0.0, 0.3, 0.5, 0.6, 0.7, 1.0],
        "fixed": {"rrf_k": 60, "n_results": 5},
        "description": "向量 vs BM25 权重消融（0.0=纯BM25, 1.0=纯向量）",
    },
    "rrf_k": {
        "values": [20, 30, 60, 100, 150],
        "fixed": {"alpha": 0.7, "n_results": 5},
        "description": "RRF 融合参数 k 消融",
    },
    "n_results": {
        "values": [1, 3, 5, 10, 20],
        "fixed": {"alpha": 0.7, "rrf_k": 60},
        "description": "返回条数消融",
    },
    "rerank_mode": {
        "values": ["off", "cross_encoder", "llm"],
        "fixed": {"alpha": 0.7, "rrf_k": 60, "n_results": 5},
        "description": "Reranker 模式消融（off=不重排, cross_encoder=CE精排, llm=LLM精排）",
    },
    "chunk_strategy": {
        "values": ["fixed", "semantic"],
        "fixed": {"alpha": 0.7, "rrf_k": 60, "n_results": 5},
        "description": "分块策略消融（需预先用不同策略重建索引）",
    },
}


def _bootstrap_ci(
    values: List[float],
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
    seed: int = 42,
) -> Dict[str, float]:
    """Bootstrap 95% 置信区间"""
    if len(values) < 3:
        mean = sum(values) / len(values) if values else 0.0
        return {"mean": round(mean, 4), "ci_lower": round(mean, 4), "ci_upper": round(mean, 4), "n": len(values)}

    rng = random.Random(seed)
    means = []
    for _ in range(n_bootstrap):
        sample = [rng.choice(values) for _ in range(len(values))]
        means.append(sum(sample) / len(sample))
    means.sort()

    alpha_half = (1 - confidence) / 2
    lo_idx = int(alpha_half * n_bootstrap)
    hi_idx = int((1 - alpha_half) * n_bootstrap) - 1
    mean = sum(values) / len(values)

    return {
        "mean": round(mean, 4),
        "ci_lower": round(means[lo_idx], 4),
        "ci_upper": round(means[hi_idx], 4),
        "n": len(values),
    }


async def run_ablation(dataset_path: str, output_path: str) -> Dict:
    all_results = {}

    for param_name, config in ABLATION_EXPERIMENTS.items():
        if param_name in ("rerank_mode", "chunk_strategy"):
            print(f"\n  跳过 {param_name}（需手动配置环境/索引后单独运行）")
            continue

        print(f"\n{'='*50}")
        print(f"消融实验: {config['description']}")
        print(f"{'='*50}")

        param_results = []
        for value in config["values"]:
            params = {**config["fixed"], param_name: value}
            print(f"  {param_name}={value} ...", end=" ", flush=True)

            metrics = await evaluate_retrieval(dataset_path=dataset_path, **params)
            param_results.append({"value": value, **metrics})
            print(
                f"Recall@5={metrics['recall@5']:.4f}  "
                f"MRR@5={metrics['mrr@5']:.4f}  "
                f"NDCG@5={metrics['ndcg@5']:.4f}  "
                f"Hit@5={metrics['hit_rate@5']:.4f}"
            )

            await asyncio.sleep(0.1)

        best = max(param_results, key=lambda r: r["recall@5"])
        per_query_recalls = best.get("per_query_recall@5", [])
        best_ci = _bootstrap_ci(per_query_recalls) if per_query_recalls else {
            "mean": best["recall@5"], "ci_lower": best["recall@5"],
            "ci_upper": best["recall@5"], "n": best.get("total_queries", 0),
        }

        for pr in param_results:
            pr.pop("per_query_recall@5", None)

        all_results[param_name] = {
            "description": config["description"],
            "best_value": best["value"],
            "best_recall@5": best["recall@5"],
            "best_recall@5_ci95": best_ci,
            "best_ndcg@5": best.get("ndcg@5", 0),
            "results": param_results,
        }

    report = {
        "timestamp": datetime.now().isoformat(),
        "note": f"样本量 N={param_results[0].get('total_queries', '?') if param_results else '?'}，置信区间为 Bootstrap 95% CI",
        "experiments": all_results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print("消融实验摘要")
    print(f"{'='*50}")
    for param, data in all_results.items():
        ci = data.get("best_recall@5_ci95", {})
        print(
            f"  {param}: 最优值={data['best_value']}  "
            f"Recall@5={data['best_recall@5']:.4f}  "
            f"NDCG@5={data.get('best_ndcg@5', 0):.4f}  "
            f"95%CI=[{ci.get('ci_lower', '?')}, {ci.get('ci_upper', '?')}]"
        )

    return report
