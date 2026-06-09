"""
ChromaDB → Milvus 数据迁移脚本

将 ChromaDB 中所有知识库的向量数据迁移到 Milvus。
支持断点续传（跳过已存在的 collection）。

用法：
    python scripts/migrate_chromadb_to_milvus.py

环境变量：
    CHROMA_SERVER_HOST (默认 127.0.0.1)
    CHROMA_SERVER_PORT (默认 8000)
    MILVUS_HOST (默认 127.0.0.1)
    MILVUS_PORT (默认 19530)
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")

import chromadb
from pymilvus import connections, utility

from app.utils.vector_store import MilvusStore


def migrate():
    chroma_host = os.getenv("CHROMA_SERVER_HOST", "127.0.0.1")
    chroma_port = int(os.getenv("CHROMA_SERVER_PORT", "8000"))
    milvus_host = os.getenv("MILVUS_HOST", "127.0.0.1")
    milvus_port = os.getenv("MILVUS_PORT", "19530")

    print(f"ChromaDB: {chroma_host}:{chroma_port}")
    print(f"Milvus:   {milvus_host}:{milvus_port}")

    chroma = chromadb.HttpClient(host=chroma_host, port=chroma_port)
    chroma.heartbeat()
    print("✅ ChromaDB 连接成功")

    os.environ["MILVUS_HOST"] = milvus_host
    os.environ["MILVUS_PORT"] = milvus_port

    milvus = MilvusStore()
    print(f"✅ Milvus 连接成功 (version: {utility.get_server_version()})")
    collections = chroma.list_collections()
    print(f"\n共 {len(collections)} 个 collection 待迁移\n")

    total_vectors = 0
    migrated = 0
    skipped = 0
    failed = 0

    for col in collections:
        name = col.name
        count = col.count()
        if count == 0:
            print(f"  ⏭ {name}: 空 collection，跳过")
            skipped += 1
            continue

        if utility.has_collection(name):
            existing = MilvusStore()
            try:
                existing_count = existing.count(name)
                if existing_count >= count:
                    print(f"  ⏭ {name}: Milvus 已有 {existing_count} 条 (ChromaDB {count} 条)，跳过")
                    skipped += 1
                    total_vectors += existing_count
                    continue
            except Exception:
                pass

        print(f"  📦 {name}: {count} vectors ... ", end="", flush=True)
        start = time.time()

        try:
            data = col.get(include=["documents", "metadatas", "embeddings"])

            ids = data.get("ids", [])
            documents = data.get("documents", [])
            metadatas = data.get("metadatas", [])
            embeddings = data.get("embeddings", [])

            if len(ids) == 0 or embeddings is None or len(embeddings) == 0:
                print("❌ 无数据")
                failed += 1
                continue

            embeddings = [list(e) for e in embeddings]

            milvus.create_collection(name)

            BATCH = 500
            for i in range(0, len(ids), BATCH):
                batch_ids = ids[i:i+BATCH]
                batch_emb = embeddings[i:i+BATCH]
                batch_doc = documents[i:i+BATCH] if documents else [""] * len(batch_ids)
                batch_meta = metadatas[i:i+BATCH] if metadatas else [{}] * len(batch_ids)
                milvus.add(name, batch_ids, batch_emb, batch_doc, batch_meta)

            elapsed = time.time() - start
            print(f"✅ {count} vectors ({elapsed:.1f}s)")
            migrated += 1
            total_vectors += count

        except Exception as e:
            print(f"❌ 失败: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"迁移完成: {migrated} 成功, {skipped} 跳过, {failed} 失败")
    print(f"总向量数: {total_vectors}")
    print(f"{'='*50}")


if __name__ == "__main__":
    migrate()
