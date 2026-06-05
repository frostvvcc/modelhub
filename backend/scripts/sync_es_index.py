"""
将 ChromaDB 中所有知识库的 chunk 数据同步到 Elasticsearch。

用法:
    cd backend
    python scripts/sync_es_index.py

适用场景:
- ES 索引为空（首次同步）
- ES 索引与 ChromaDB 数据不一致
- ES 重装后需要重建索引
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.database_async import AsyncSessionLocal
from app.models.vector_db import VectorDb
from app.utils.optimized_chromadb import get_chromadb_client
from app.utils.logger_config import get_logger

logger = get_logger("sync_es_index")


async def sync_all():
    from app.services.rag.es_retrieval import (
        ES_ENABLED, get_es_client, ensure_index, index_chunks, _index_name,
    )

    if not ES_ENABLED:
        print("ES_ENABLED=false，跳过同步")
        return

    client = await get_es_client()
    if not client:
        print("Elasticsearch 连接失败，请确保 ES 已启动")
        return
    print("Elasticsearch 连接成功\n")

    chroma = get_chromadb_client()
    if not chroma:
        print("ChromaDB 连接失败")
        return
    print("ChromaDB 连接成功\n")

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(VectorDb))
        vector_dbs = result.scalars().all()

    total_chunks = 0
    synced_dbs = 0

    for vdb in vector_dbs:
        collection_name = f"vector_db_{vdb.id}"
        try:
            collection = chroma.get_collection(name=collection_name)
            data = collection.get(include=["documents", "metadatas"])
        except Exception:
            print(f"  [{vdb.id}] {vdb.name}: ChromaDB 集合不存在，跳过")
            continue

        docs = data.get("documents") or []
        metas = data.get("metadatas") or [{}] * len(docs)
        ids = data.get("ids") or []

        if not docs:
            print(f"  [{vdb.id}] {vdb.name}: 无 chunk 数据，跳过")
            continue

        idx_name = _index_name(vdb.id)
        if await client.indices.exists(index=idx_name):
            await client.indices.delete(index=idx_name)

        if not await ensure_index(vdb.id):
            print(f"  [{vdb.id}] {vdb.name}: ES 索引创建失败")
            continue

        chunks = []
        for i, (doc_text, meta, chunk_id) in enumerate(zip(docs, metas, ids)):
            chunks.append({
                "chunk_id": chunk_id,
                "content": doc_text,
                "source": meta.get("source", ""),
                "document_id": str(meta.get("document_id", "")),
            })

        written = await index_chunks(vdb.id, chunks)
        total_chunks += written
        synced_dbs += 1
        print(f"  [{vdb.id}] {vdb.name}: {written} chunks 已同步到 ES")

    print(f"\n{'='*50}")
    print(f"同步完成: {synced_dbs} 个知识库, {total_chunks} 个 chunks")
    print(f"{'='*50}")


if __name__ == "__main__":
    print("=" * 50)
    print("Elasticsearch 全量索引同步")
    print("=" * 50)
    print()
    asyncio.run(sync_all())
