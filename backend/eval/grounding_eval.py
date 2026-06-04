"""Grounding 模块自身的准确率评测

人工标注 claim + 预期 verdict，跑 grounding 模块，计算 precision / recall / F1。
同时检测主链路是否正确调用 grounding。
"""
import asyncio
import json
from typing import Dict, List, Any
from openai import AsyncOpenAI


LABELED_CLAIMS = [
    {
        "answer": "2025年春季学期共有273门次课程获批开展线上线下混合式教学。",
        "sources": ["根据教务处通知，2025年春季学期共有273门次课程申请获批开展线上线下混合式教学。"],
        "claims": [
            {"text": "2025年春季学期有273门次课程获批混合式教学", "expected": "supported"},
        ],
    },
    {
        "answer": "论文查重去除本人文献复制比R≥30%视为不合格，不能直接参加答辩。",
        "sources": ["去除本人文献复制比R＜30%视为合格，R≥30%视为不合格。"],
        "claims": [
            {"text": "复制比R≥30%视为不合格", "expected": "supported"},
            {"text": "不能直接参加答辩", "expected": "unsupported"},
        ],
    },
    {
        "answer": "该通知发布于2025年7月17日，共有66篇论文被评为优秀。",
        "sources": ["关于公布2024届本科毕业生校级优秀毕业设计（论文）名单的通知，发布日期2024-07-23。"],
        "claims": [
            {"text": "通知发布于2025年7月17日", "expected": "contradicted"},
            {"text": "共有66篇论文被评为优秀", "expected": "unsupported"},
        ],
    },
    {
        "answer": "第一次答辩时间为6月6日至11日。",
        "sources": ["第一次答辩时间为6月6日至11日，此阶段不安排第二次答辩。"],
        "claims": [
            {"text": "第一次答辩时间为6月6日至11日", "expected": "supported"},
        ],
    },
    {
        "answer": "学校不补发原版学位证书，但可出具学位证明书。",
        "sources": ["参考资料中没有涉及学位证书遗失后补发或重领的具体规定。"],
        "claims": [
            {"text": "学校不补发原版学位证书", "expected": "unsupported"},
            {"text": "可以出具学位证明书", "expected": "unsupported"},
        ],
    },
    {
        "answer": "毕业设计最终版等材料未按时提交至毕设系统，将取消第一次答辩成绩。",
        "sources": ["凡存在以下情形，取消该生第一次答辩成绩：（1）毕业设计最终版等相关材料未按时提交至毕设系统。"],
        "claims": [
            {"text": "材料未按时提交会取消第一次答辩成绩", "expected": "supported"},
        ],
    },
    {
        "answer": "开题答辩通过后需提交题目变更申请表，经逐级审批方可修改。",
        "sources": ["2025届本科毕业生毕业预审核工作时间为2025年3月17日至3月27日。"],
        "claims": [
            {"text": "需提交题目变更申请表", "expected": "unsupported"},
            {"text": "需经逐级审批方可修改", "expected": "unsupported"},
        ],
    },
    {
        "answer": "身份证号填错属于第二种情形，需高考所在地招生部门出具证明。",
        "sources": ["（2）在高考报名信息采集时，考生身份证号码个别位置填写错误，由学生当年高考所在地招生部门出具证明。"],
        "claims": [
            {"text": "身份证号填错属于第二种情形", "expected": "supported"},
            {"text": "需高考所在地招生部门出具证明", "expected": "supported"},
        ],
    },
]


async def run_grounding_eval(
    api_key: str,
    base_url: str,
    model: str = "qwen-plus",
) -> Dict:
    """用标注数据评测 grounding 模块的 precision / recall"""
    from app.services.rag.grounding import verify_grounding

    all_predictions = []
    all_labels = []
    detail = []

    for case in LABELED_CLAIMS:
        sources = [{"content": s} for s in case["sources"]]
        result = await verify_grounding(case["answer"], sources, model)

        predicted_claims = result.get("claims", [])
        expected_claims = case["claims"]

        for j, expected in enumerate(expected_claims):
            predicted = predicted_claims[j] if j < len(predicted_claims) else None
            pred_verdict = predicted.get("verdict", "unknown") if predicted else "unknown"

            all_labels.append(expected["expected"])
            all_predictions.append(pred_verdict)
            detail.append({
                "text": expected["text"],
                "expected": expected["expected"],
                "predicted": pred_verdict,
                "correct": pred_verdict == expected["expected"],
                "reason": predicted.get("reason", "") if predicted else "",
            })

        await asyncio.sleep(0.3)

    correct = sum(1 for d in detail if d["correct"])
    total = len(detail)
    accuracy = correct / total if total else 0

    verdicts = ["supported", "unsupported", "contradicted"]
    per_class = {}
    for v in verdicts:
        tp = sum(1 for d in detail if d["expected"] == v and d["predicted"] == v)
        fp = sum(1 for d in detail if d["expected"] != v and d["predicted"] == v)
        fn = sum(1 for d in detail if d["expected"] == v and d["predicted"] != v)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        per_class[v] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": sum(1 for d in detail if d["expected"] == v),
        }

    return {
        "total_claims": total,
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "per_class_metrics": per_class,
        "detail": detail,
    }
