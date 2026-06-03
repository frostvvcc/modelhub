#!/usr/bin/env python3
"""
ModelHub RAG 三层评测体系入口脚本

使用方式:
  # 生成评测集（LLM 自动生成问题）
  python scripts/run_rag_eval.py --mode generate --vector-db-id 11

  # Layer 1：分块质量评测
  python scripts/run_rag_eval.py --mode chunk --vector-db-id 11

  # Layer 2：单次检索评测
  python scripts/run_rag_eval.py --mode retrieval --alpha 0.7

  # Layer 2：消融实验
  python scripts/run_rag_eval.py --mode ablation

  # 全量（Layer 1 + 生成评测集 + Layer 2 消融）
  python scripts/run_rag_eval.py --mode full --vector-db-id 11
"""
import asyncio
import argparse
import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")


def get_llm_config():
    return {
        "api_key": os.getenv("EMBEDDING_API_KEY", ""),
        "base_url": os.getenv("EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "model": os.getenv("EVAL_LLM_MODEL", "qwen-plus"),
    }


async def main():
    parser = argparse.ArgumentParser(description="ModelHub RAG 三层评测")
    parser.add_argument("--mode", choices=["generate", "chunk", "retrieval", "ablation", "e2e", "full"],
                        default="retrieval", help="评测模式")
    parser.add_argument("--vector-db-id", type=int, default=11, help="知识库 ID")
    parser.add_argument("--dataset", default="eval/dataset.json", help="评测集路径")
    parser.add_argument("--output", default="eval/report.json", help="报告输出路径")
    parser.add_argument("--alpha", type=float, default=0.7)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--n-results", type=int, default=5)
    parser.add_argument("--sample-size", type=int, default=30, help="分块评测采样数量")
    parser.add_argument("--eval-count", type=int, default=50, help="评测集条数")
    args = parser.parse_args()

    llm_config = get_llm_config()
    dataset_path = str(project_root / args.dataset)
    output_path = str(project_root / args.output)

    if args.mode == "generate":
        print(f"\n=== 生成评测集 (vector_db_{args.vector_db_id}, {args.eval_count} 条) ===\n")
        from eval.dataset_generator import generate_dataset
        await generate_dataset(
            vector_db_id=args.vector_db_id,
            n=args.eval_count,
            output_path=dataset_path,
            **llm_config,
        )

    elif args.mode == "chunk":
        print(f"\n=== Layer 1: 分块质量评测 (vector_db_{args.vector_db_id}) ===\n")
        from eval.chunk_eval import evaluate_chunk_quality
        result = await evaluate_chunk_quality(
            vector_db_id=args.vector_db_id,
            sample_size=args.sample_size,
            **llm_config,
        )
        print(f"\n结果:")
        for k, v in result.items():
            print(f"  {k}: {v}")

    elif args.mode == "retrieval":
        print(f"\n=== Layer 2: 单次检索评测 (alpha={args.alpha}) ===\n")
        from eval.runner import evaluate_retrieval
        metrics = await evaluate_retrieval(
            dataset_path=dataset_path,
            alpha=args.alpha,
            n_results=args.n_results,
            rrf_k=args.rrf_k,
        )
        print(f"\n结果:")
        for k, v in metrics.items():
            print(f"  {k}: {v}")

    elif args.mode == "ablation":
        print(f"\n=== Layer 2: 消融实验 ===\n")
        from eval.ablation import run_ablation
        await run_ablation(dataset_path=dataset_path, output_path=output_path)
        print(f"\n报告已保存: {output_path}")

    elif args.mode == "e2e":
        print(f"\n=== Layer 3: 端到端回答质量评测 ===\n")
        from eval.e2e_eval import run_e2e_eval
        result = await run_e2e_eval(
            dataset_path=dataset_path,
            vector_db_id=args.vector_db_id,
            alpha=args.alpha,
            n_results=args.n_results,
            **llm_config,
        )
        e2e_path = str(project_root / "eval" / "e2e_report.json")
        import json
        with open(e2e_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n=== 回答质量评测结果 ===")
        for dim, scores in result.get("dimension_scores", {}).items():
            print(f"  {dim}: avg={scores['avg']} (min={scores['min']}, max={scores['max']})")
        print(f"  幻觉率: {result.get('hallucination_rate', '?')}")
        print(f"\n报告已保存: {e2e_path}")

    elif args.mode == "full":
        print(f"\n{'='*60}")
        print(f"  ModelHub RAG 三层评测 (vector_db_{args.vector_db_id})")
        print(f"{'='*60}\n")

        # Layer 1
        print("--- Layer 1: 分块质量评测 ---\n")
        from eval.chunk_eval import evaluate_chunk_quality
        chunk_result = await evaluate_chunk_quality(
            vector_db_id=args.vector_db_id,
            sample_size=args.sample_size,
            **llm_config,
        )
        print(f"\n  平均语义完整度: {chunk_result.get('avg_completeness', '?')}/5")
        print(f"  分数分布: {chunk_result.get('score_distribution', {})}\n")

        # 生成评测集
        print("--- 生成评测集 ---\n")
        from eval.dataset_generator import generate_dataset
        await generate_dataset(
            vector_db_id=args.vector_db_id,
            n=args.eval_count,
            output_path=dataset_path,
            **llm_config,
        )

        # Layer 2
        print("\n--- Layer 2: 消融实验 ---")
        from eval.ablation import run_ablation
        ablation_path = str(project_root / "eval" / "ablation_report.json")
        await run_ablation(dataset_path=dataset_path, output_path=ablation_path)

        print(f"\n{'='*60}")
        print("  评测完成！")
        print(f"  分块质量报告: 平均完整度 {chunk_result.get('avg_completeness', '?')}/5")
        print(f"  消融实验报告: {ablation_path}")
        print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
