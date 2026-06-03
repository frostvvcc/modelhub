"""
Ragas 自动化 RAG 评测

使用行业标准 Ragas 框架评测 RAG 管线质量，输出三个核心指标：
  - Context Precision：检索结果中相关文档的排名是否靠前
  - Faithfulness：生成答案是否忠实于检索到的上下文（幻觉检测）
  - Answer Relevancy：生成答案与用户问题的相关度

使用方式：
    python -m eval.ragas_eval --vector-db-id 1 --dataset eval/dataset.json

依赖：pip install ragas datasets
"""
import os
import sys
import json
import asyncio
import argparse
import logging
from typing import List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def load_dataset(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def generate_rag_answers(
    questions: List[str],
    vector_db_id: int,
) -> List[Dict]:
    """对每个问题跑一次 RAG 检索 + LLM 生成，收集 (question, contexts, answer) 三元组"""
    from app.services.rag.retrieval import VectorRetriever

    results = []
    for i, q in enumerate(questions):
        try:
            retrieval_results = await VectorRetriever.hybrid_query(vector_db_id, q, n_results=5)
            contexts = [r.content for r in retrieval_results]

            from openai import AsyncOpenAI
            from app.config import settings
            client = AsyncOpenAI(api_key=settings.embedding_api_key, base_url=settings.embedding_base_url)
            ctx_text = "\n\n".join(f"[来源{j+1}] {c[:500]}" for j, c in enumerate(contexts))
            resp = await client.chat.completions.create(
                model="qwen-plus",
                messages=[
                    {"role": "system", "content": f"根据以下资料回答问题，引用来源编号。\n\n{ctx_text}"},
                    {"role": "user", "content": q},
                ],
                max_tokens=500,
                temperature=0.0,
            )
            answer = resp.choices[0].message.content.strip()

            results.append({
                "question": q,
                "contexts": contexts,
                "answer": answer,
            })
            logger.info(f"[{i+1}/{len(questions)}] {q[:40]}... → {len(contexts)} contexts")
        except Exception as e:
            logger.error(f"问题 '{q[:30]}' 评测失败: {e}")
            results.append({"question": q, "contexts": [], "answer": ""})

    return results


def run_ragas_evaluation(
    rag_results: List[Dict],
    ground_truths: List[str] = None,
) -> Dict:
    """用 Ragas 框架计算评测指标（兼容 ragas >= 0.2）"""
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import ContextPrecision, Faithfulness, AnswerRelevancy

    # ragas >= 0.2 字段名：user_input, retrieved_contexts, response, reference
    data = {
        "user_input": [r["question"] for r in rag_results],
        "retrieved_contexts": [r["contexts"] for r in rag_results],
        "response": [r["answer"] for r in rag_results],
    }
    if ground_truths and any(ground_truths):
        data["reference"] = ground_truths

    dataset = Dataset.from_dict(data)

    metrics = [ContextPrecision(), Faithfulness(), AnswerRelevancy()]
    result = evaluate(dataset=dataset, metrics=metrics)

    scores = {
        "context_precision": round(result["context_precision"], 4),
        "faithfulness": round(result["faithfulness"], 4),
        "answer_relevancy": round(result["answer_relevancy"], 4),
    }

    logger.info(f"Ragas 评测结果: {json.dumps(scores, ensure_ascii=False)}")
    return scores


def main():
    parser = argparse.ArgumentParser(description="Ragas RAG 评测")
    parser.add_argument("--vector-db-id", type=int, required=True)
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--output", type=str, default="eval/ragas_report.json")
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    questions = [item["question"] for item in dataset]
    ground_truths = [item.get("ground_truth", "") for item in dataset]

    rag_results = asyncio.run(generate_rag_answers(questions, args.vector_db_id))

    scores = run_ragas_evaluation(
        rag_results,
        ground_truths=ground_truths if any(ground_truths) else None,
    )

    report = {
        "vector_db_id": args.vector_db_id,
        "num_questions": len(questions),
        "scores": scores,
        "details": rag_results,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\nRagas 评测完成:")
    print(f"  Context Precision: {scores['context_precision']}")
    print(f"  Faithfulness:      {scores['faithfulness']}")
    print(f"  Answer Relevancy:  {scores['answer_relevancy']}")
    print(f"\n详细报告: {args.output}")


if __name__ == "__main__":
    main()
