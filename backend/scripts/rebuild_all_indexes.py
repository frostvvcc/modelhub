"""
重建所有知识库的向量索引（新分块参数: chunk_size=800, overlap=150）

用法:
    cd ModelHub-backend
    python scripts/rebuild_all_indexes.py

会依次处理每个知识库中每个文档:
1. 删除 ChromaDB 中旧的向量
2. 用新参数重新分块 + embedding
3. 写入 ChromaDB

同时更新所有知识库的 document_similarity 阈值 0.70 → 0.50
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update
from app.database_async import AsyncSessionLocal
from app.models.vector_db import VectorDb
from app.models.document import Document
from app.services.vector_service import AsyncVectorService
from app.services.rag.retrieval import invalidate_bm25_cache
from app.utils.optimized_chromadb import get_chromadb_client
from app.utils.logger_config import get_logger

logger = get_logger("rebuild_indexes")

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
CHUNK_STRATEGY = "fixed"
NEW_SIMILARITY_THRESHOLD = 0.50


async def rebuild_all():
    async with AsyncSessionLocal() as session:
        # 1. 更新所有知识库的 document_similarity 阈值
        result = await session.execute(select(VectorDb))
        vector_dbs = result.scalars().all()

        updated_count = 0
        for vdb in vector_dbs:
            old_val = float(vdb.document_similarity) if vdb.document_similarity else 0.0
            if old_val > NEW_SIMILARITY_THRESHOLD:
                vdb.document_similarity = NEW_SIMILARITY_THRESHOLD
                updated_count += 1
                print(f"  知识库 [{vdb.id}] {vdb.name}: 阈值 {old_val:.2f} → {NEW_SIMILARITY_THRESHOLD:.2f}")
        if updated_count:
            await session.commit()
        print(f"\n✅ 已更新 {updated_count}/{len(vector_dbs)} 个知识库的相似度阈值\n")

        # 2. 逐个知识库重建索引
        total_docs = 0
        success_docs = 0
        failed_docs = 0
        skipped_docs = 0

        for vdb in vector_dbs:
            docs_result = await session.execute(
                select(Document).where(
                    Document.vector_db_id == vdb.id,
                    Document.is_folder == False,
                    Document.status.in_(["success", "failed"]),
                )
            )
            docs = docs_result.scalars().all()
            if not docs:
                print(f"📂 知识库 [{vdb.id}] {vdb.name}: 无文档，跳过")
                continue

            print(f"\n📂 知识库 [{vdb.id}] {vdb.name}: {len(docs)} 个文档待重建")

            await AsyncVectorService.ensure_collection_exists(vdb.id)

            for doc in docs:
                total_docs += 1

                if not doc.save_path or not os.path.exists(doc.save_path):
                    print(f"  ⚠️  [{doc.id}] {doc.name}: 原始文件不存在，跳过")
                    skipped_docs += 1
                    continue

                print(f"  🔄 [{doc.id}] {doc.name} ...", end=" ", flush=True)

                try:
                    # 删除旧向量
                    await AsyncVectorService._delete_document_vectors(vdb.id, doc.id)

                    # 用新参数重建
                    await asyncio.to_thread(
                        AsyncVectorService._process_and_add_file,
                        vdb.id,
                        doc.save_path,
                        doc.id,
                        doc.folder_path,
                        doc.parent_id,
                        CHUNK_STRATEGY,
                        CHUNK_SIZE,
                        CHUNK_OVERLAP,
                    )

                    doc.status = "success"
                    doc.error_message = None
                    await session.merge(doc)
                    await session.commit()
                    success_docs += 1
                    print("✅")

                except Exception as exc:
                    doc.status = "failed"
                    doc.error_message = f"重建索引失败: {str(exc)[:500]}"
                    await session.merge(doc)
                    await session.commit()
                    failed_docs += 1
                    print(f"❌ {exc}")

            invalidate_bm25_cache(vdb.id)

    print(f"\n{'='*50}")
    print(f"重建完成!")
    print(f"  总计: {total_docs} 个文档")
    print(f"  成功: {success_docs}")
    print(f"  失败: {failed_docs}")
    print(f"  跳过: {skipped_docs} (文件不存在)")
    print(f"  新参数: chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}")
    print(f"{'='*50}")


if __name__ == "__main__":
    print("=" * 50)
    print("知识库向量索引全量重建")
    print(f"新参数: chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}, strategy={CHUNK_STRATEGY}")
    print(f"新阈值: document_similarity={NEW_SIMILARITY_THRESHOLD}")
    print("=" * 50)
    print()

    client = get_chromadb_client()
    if not client:
        print("❌ ChromaDB 连接失败，请确保 ChromaDB 服务已启动")
        sys.exit(1)
    print("✅ ChromaDB 连接成功\n")

    asyncio.run(rebuild_all())
