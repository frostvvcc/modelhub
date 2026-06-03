"""Layer 1：分块质量评测 — 评估 chunk 的语义完整度"""
import asyncio
import random
from typing import List, Dict
from openai import AsyncOpenAI


async def score_chunk(client: AsyncOpenAI, model: str, content: str) -> int:
    prompt = (
        "请评估这段文本的信息完整度（1-5 分）：\n"
        "- 5分：包含完整的一个知识点，不需要额外上下文就能理解\n"
        "- 4分：基本完整，有少量上下文缺失但不影响核心理解\n"
        "- 3分：包含部分信息，但缺少关键上下文\n"
        "- 2分：信息不完整，需要额外上下文才能理解\n"
        "- 1分：信息被截断，无法独立理解\n\n"
        f"文本：\n{content[:500]}\n\n只输出一个数字（1-5）："
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0.0,
        )
        text = resp.choices[0].message.content.strip()
        score = int(text[0])
        return min(5, max(1, score))
    except Exception:
        return 0


async def evaluate_chunk_quality(
    vector_db_id: int,
    sample_size: int = 30,
    api_key: str = "",
    base_url: str = "",
    model: str = "qwen-plus",
) -> Dict:
    import chromadb
    chroma = chromadb.HttpClient(host="127.0.0.1", port=8000)
    col = chroma.get_collection(f"vector_db_{vector_db_id}")
    all_data = col.get(include=["documents"])

    docs = all_data["documents"]
    if not docs:
        return {"error": "知识库为空"}

    sampled = random.sample(docs, min(sample_size, len(docs)))
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    scores = []
    for i, chunk in enumerate(sampled):
        print(f"  [{i+1}/{len(sampled)}] 评估语义完整度...", end=" ", flush=True)
        score = await score_chunk(client, model, chunk)
        if score > 0:
            scores.append(score)
            print(f"得分: {score}")
        else:
            print("跳过（评分失败）")
        await asyncio.sleep(0.3)

    if not scores:
        return {"error": "所有评分都失败了"}

    distribution = {i: scores.count(i) for i in range(1, 6)}
    avg = sum(scores) / len(scores)

    return {
        "vector_db_id": vector_db_id,
        "total_chunks": len(docs),
        "sample_size": len(scores),
        "avg_completeness": round(avg, 2),
        "score_distribution": distribution,
        "avg_chunk_length": round(sum(len(d) for d in docs) / len(docs)),
        "min_chunk_length": min(len(d) for d in docs),
        "max_chunk_length": max(len(d) for d in docs),
    }
