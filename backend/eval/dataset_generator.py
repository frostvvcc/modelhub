"""评测集自动生成器 — 从 ChromaDB 抽 chunk，用 LLM 生成问题"""
import asyncio
import json
import random
from pathlib import Path
from typing import List, Dict, Optional
from openai import AsyncOpenAI


async def generate_question(client: AsyncOpenAI, model: str, chunk_content: str) -> Optional[str]:
    prompt = (
        "基于以下文档片段，生成一个学生可能会问的自然问题。\n"
        "要求：\n"
        "1. 问题要像真实用户会问的，口语化\n"
        "2. 不要直接复制文档原文里的关键词（模拟用词不同的情况）\n"
        "3. 只输出问题本身，不要任何前缀或解释\n\n"
        f"文档片段：\n{chunk_content[:600]}"
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.8,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"  生成问题失败: {e}")
        return None


async def generate_dataset(
    vector_db_id: int,
    n: int = 50,
    api_key: str = "",
    base_url: str = "",
    model: str = "qwen-plus",
    output_path: str = "eval/dataset.json",
):
    import chromadb
    chroma = chromadb.HttpClient(host="127.0.0.1", port=8000)
    col = chroma.get_collection(f"vector_db_{vector_db_id}")
    all_data = col.get(include=["documents", "metadatas"])

    docs = all_data["documents"]
    metas = all_data["metadatas"] or [{}] * len(docs)
    ids = all_data["ids"]

    if len(docs) < 5:
        print(f"知识库 vector_db_{vector_db_id} 只有 {len(docs)} 个 chunk，数据不足")
        return

    indices = random.sample(range(len(docs)), min(n * 2, len(docs)))
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    dataset_items = []
    for idx in indices:
        if len(dataset_items) >= n:
            break

        content = docs[idx]
        meta = metas[idx] or {}
        if len(content.strip()) < 50:
            continue

        print(f"  [{len(dataset_items)+1}/{n}] 生成问题 (doc_id={meta.get('document_id','?')})...", end=" ")
        question = await generate_question(client, model, content)
        if not question:
            continue

        print(f"OK: {question[:50]}")
        dataset_items.append({
            "id": len(dataset_items) + 1,
            "query": question,
            "relevant_document_ids": [str(meta.get("document_id", ""))],
            "relevant_chunk_ids": [ids[idx]],
            "source_content_preview": content[:200],
            "source_name": meta.get("source", "unknown"),
        })

        await asyncio.sleep(0.3)

    dataset = {
        "version": "2.0",
        "vector_db_id": vector_db_id,
        "total_items": len(dataset_items),
        "items": dataset_items,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    print(f"\n评测集已保存: {output_path} ({len(dataset_items)} 条)")
    return dataset
