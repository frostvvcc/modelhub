"""消融实验 — 每次只变一个参数，观察独立影响"""
import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any
from eval.runner import evaluate_retrieval

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
}


async def run_ablation(dataset_path: str, output_path: str) -> Dict:
    all_results = {}

    for param_name, config in ABLATION_EXPERIMENTS.items():
        print(f"\n{'='*50}")
        print(f"消融实验: {config['description']}")
        print(f"{'='*50}")

        param_results = []
        for value in config["values"]:
            params = {**config["fixed"], param_name: value}
            print(f"  {param_name}={value} ...", end=" ", flush=True)

            metrics = await evaluate_retrieval(dataset_path=dataset_path, **params)
            param_results.append({"value": value, **metrics})
            print(f"Recall@5={metrics['recall@5']:.4f}  MRR@5={metrics['mrr@5']:.4f}  Hit@5={metrics['hit_rate@5']:.4f}")

            await asyncio.sleep(0.1)

        best = max(param_results, key=lambda r: r["recall@5"])
        all_results[param_name] = {
            "description": config["description"],
            "best_value": best["value"],
            "best_recall@5": best["recall@5"],
            "results": param_results,
        }

    report = {
        "timestamp": datetime.now().isoformat(),
        "experiments": all_results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print("消融实验摘要")
    print(f"{'='*50}")
    for param, data in all_results.items():
        print(f"  {param}: 最优值={data['best_value']}  Recall@5={data['best_recall@5']:.4f}")

    return report
