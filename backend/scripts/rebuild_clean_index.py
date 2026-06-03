#!/usr/bin/env python3
"""
知识库数据清洗重建脚本

读取 ChromaDB 中的现有 chunk → 清洗 → 过滤 → 重新 embedding → 写回。
清洗前自动备份原始数据到 JSON 文件。
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")


async def rebuild_collection(vector_db_id: int, dry_run: bool = False):
    """清洗并重建单个知识库的向量索引"""
    import chromadb
    from app.services.rag.document_parser import clean_web_text, is_worth_indexing
    from app.utils.async_embedding import get_query_embedding_async

    client = chromadb.HttpClient(host="127.0.0.1", port=8000)
    col_name = f"vector_db_{vector_db_id}"

    try:
        col = client.get_collection(col_name)
    except Exception as e:
        print(f"  获取集合失败: {e}")
        return None

    all_data = col.get(include=["documents", "metadatas"])
    docs = all_data["documents"]
    metas = all_data["metadatas"] or [{}] * len(docs)
    ids = all_data["ids"]

    if not docs:
        print(f"  知识库为空，跳过")
        return None

    # 备份原始数据
    backup_dir = project_root / "eval" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{col_name}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump({"ids": ids, "documents": docs, "metadatas": metas}, f, ensure_ascii=False)
    print(f"  已备份到: {backup_path}")

    # 清洗
    cleaned_items = []
    rejected = 0
    for i in range(len(docs)):
        original = docs[i]
        cleaned = clean_web_text(original)
        if is_worth_indexing(cleaned):
            cleaned_items.append({
                "id": ids[i],
                "document": cleaned,
                "metadata": metas[i] or {},
            })
        else:
            rejected += 1

    print(f"  原始: {len(docs)} chunks → 清洗后保留: {len(cleaned_items)} | 拦截: {rejected}")

    if dry_run:
        print(f"  [DRY RUN] 不写入，仅预览")
        return {"original": len(docs), "kept": len(cleaned_items), "rejected": rejected}

    # 删除旧集合并重建
    try:
        client.delete_collection(col_name)
    except Exception:
        pass

    new_col = client.get_or_create_collection(
        name=col_name,
        metadata={"hnsw:space": "l2"},
    )

    # 分批 embedding + 写入
    batch_size = 10
    total_written = 0
    for start in range(0, len(cleaned_items), batch_size):
        batch = cleaned_items[start:start + batch_size]
        batch_ids = [item["id"] for item in batch]
        batch_docs = [item["document"] for item in batch]
        batch_metas = [item["metadata"] for item in batch]

        embeddings = []
        for doc in batch_docs:
            emb = await get_query_embedding_async(doc[:2000])
            embeddings.append(emb)
            await asyncio.sleep(0.1)

        new_col.add(
            ids=batch_ids,
            documents=batch_docs,
            metadatas=batch_metas,
            embeddings=embeddings,
        )
        total_written += len(batch)
        print(f"  写入进度: {total_written}/{len(cleaned_items)}")

    print(f"  重建完成: {col_name} ({total_written} chunks)")
    return {"original": len(docs), "kept": total_written, "rejected": rejected}


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="知识库清洗重建")
    parser.add_argument("--db-ids", type=str, required=True,
                        help="要重建的知识库 ID，逗号分隔，如 10,11")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅预览，不实际写入")
    args = parser.parse_args()

    db_ids = [int(x.strip()) for x in args.db_ids.split(",")]

    print(f"\n{'='*50}")
    print(f"  知识库清洗重建 {'(DRY RUN)' if args.dry_run else ''}")
    print(f"  目标: {db_ids}")
    print(f"{'='*50}\n")

    results = {}
    for db_id in db_ids:
        print(f"\n--- vector_db_{db_id} ---")
        result = await rebuild_collection(db_id, dry_run=args.dry_run)
        if result:
            results[db_id] = result

    print(f"\n{'='*50}")
    print("  重建摘要")
    print(f"{'='*50}")
    for db_id, r in results.items():
        print(f"  vector_db_{db_id}: {r['original']} → {r['kept']} chunks (拦截 {r['rejected']})")


if __name__ == "__main__":
    asyncio.run(main())
