"""
文档入库异步任务

将耗时的文档解析 → 分块 → Embedding → 向量入库 → 三元组抽取流程
从同步请求中解耦，上传接口立即返回 task_id，后台 Worker 异步处理。

支持：进度上报（self.update_state）、失败自动重试（指数退避 3 次）、
任务状态查询（PENDING → STARTED → PROGRESS → SUCCESS / FAILURE）。
"""
import logging
from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="document.process",
    max_retries=3,
    default_retry_delay=10,
    acks_late=True,
)
def process_document_task(
    self,
    vector_db_id: int,
    file_path: str,
    document_id: int,
    folder_hierarchy: str = None,
    parent_id: int = None,
    chunk_strategy: str = "markdown",
    chunk_size: int = 800,
    chunk_overlap: int = 150,
):
    """
    异步文档入库任务。

    上传接口调用：
        task = process_document_task.delay(vector_db_id, file_path, document_id, ...)
        return {"task_id": task.id}

    前端轮询：
        GET /tasks/{task_id} → {"state": "PROGRESS", "progress": 60, "step": "embedding"}
    """
    try:
        self.update_state(state="PROGRESS", meta={"progress": 0, "step": "parsing"})

        from app.utils.optimized_chromadb import get_chromadb_client
        from app.utils.EmbbedingModel import ChatEmbeddings
        from app.services.rag.document_parser import extract_text, clean_web_text, clean_document_text, is_worth_indexing, is_quality_chunk
        from app.services.rag.chunking import split_text_into_chunks, split_parent_child, split_contextual, ChunkStrategy
        from app.config import settings
        import os

        client = get_chromadb_client()
        if not client:
            raise RuntimeError("ChromaDB 服务不可用")
        collection = client.get_collection(f"vector_db_{vector_db_id}")

        text_content = extract_text(file_path)
        if not text_content or not text_content.strip():
            raise RuntimeError(f"文件内容为空: {os.path.basename(file_path)}")

        source_ext = os.path.splitext(file_path)[1].lower()
        if source_ext == '.txt':
            text_content = clean_web_text(text_content)
        else:
            text_content = clean_document_text(text_content)
        if not is_worth_indexing(text_content):
            raise RuntimeError(f"文件清洗后有效内容不足: {os.path.basename(file_path)}")

        self.update_state(state="PROGRESS", meta={"progress": 20, "step": "chunking"})

        try:
            strategy = ChunkStrategy(chunk_strategy)
        except ValueError:
            strategy = ChunkStrategy.FIXED

        safe_chunk_size = max(100, min(int(chunk_size or 800), 4000))
        safe_overlap = max(0, min(int(chunk_overlap or 150), safe_chunk_size - 1))

        embedding_model = ChatEmbeddings(
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
        )

        chunks = []
        pc_chunks = []

        if strategy == ChunkStrategy.PARENT_CHILD:
            child_size = max(100, safe_chunk_size // 4)
            pc_chunks = split_parent_child(text_content, parent_size=safe_chunk_size, child_size=child_size)
            total = len(pc_chunks)

            self.update_state(state="PROGRESS", meta={"progress": 30, "step": "embedding", "total_chunks": total})

            child_texts = [pc.child_content for pc in pc_chunks]
            all_embeddings = embedding_model._get_text_embeddings(child_texts)

            all_ids = [f"{document_id}_chunk_{i}" for i in range(total)]
            all_documents = child_texts
            all_metadatas = []
            for i, pc in enumerate(pc_chunks):
                metadata = {
                    "source": os.path.basename(file_path),
                    "chunk_id": i,
                    "total_chunks": total,
                    "document_id": str(document_id),
                    "chunk_strategy": "parent_child",
                    "parent_content": pc.parent_content,
                    "parent_index": pc.parent_index,
                    "child_index": pc.child_index,
                    "is_child_chunk": True,
                }
                if folder_hierarchy:
                    metadata["folder_hierarchy"] = folder_hierarchy
                if parent_id:
                    metadata["parent_id"] = str(parent_id)
                all_metadatas.append(metadata)

            collection.add(
                embeddings=all_embeddings,
                documents=all_documents,
                metadatas=all_metadatas,
                ids=all_ids,
            )

            self.update_state(state="PROGRESS", meta={
                "progress": 90, "step": "embedding",
                "current": total, "total_chunks": total,
            })
        elif strategy == ChunkStrategy.CONTEXTUAL:
            import asyncio
            _ctx_loop = asyncio.new_event_loop()
            ctx_chunks = _ctx_loop.run_until_complete(split_contextual(
                text_content, chunk_size=safe_chunk_size, overlap=safe_overlap,
            ))
            _ctx_loop.close()
            total = len(ctx_chunks)

            self.update_state(state="PROGRESS", meta={"progress": 30, "step": "embedding", "total_chunks": total})

            texts_to_embed = [c.contextualized_content for c in ctx_chunks]
            all_embeddings = embedding_model._get_text_embeddings(texts_to_embed)

            all_ids = [f"{document_id}_chunk_{i}" for i in range(total)]
            all_documents = [c.original_content for c in ctx_chunks]
            all_metadatas = []
            for i, c in enumerate(ctx_chunks):
                metadata = {
                    "source": os.path.basename(file_path),
                    "chunk_id": i,
                    "total_chunks": total,
                    "document_id": str(document_id),
                    "chunk_strategy": "contextual",
                    "context_prefix": c.context_prefix,
                }
                if folder_hierarchy:
                    metadata["folder_hierarchy"] = folder_hierarchy
                if parent_id:
                    metadata["parent_id"] = str(parent_id)
                all_metadatas.append(metadata)

            collection.add(
                embeddings=all_embeddings,
                documents=all_documents,
                metadatas=all_metadatas,
                ids=all_ids,
            )
            chunks = all_documents

            self.update_state(state="PROGRESS", meta={
                "progress": 90, "step": "embedding",
                "current": total, "total_chunks": total,
            })
        else:
            chunks = split_text_into_chunks(text_content, strategy=strategy, chunk_size=safe_chunk_size, overlap=safe_overlap)
            original_count = len(chunks)
            chunks = [c for c in chunks if is_quality_chunk(c)]
            if len(chunks) < original_count:
                logger.info(f"[Celery] Chunk 质量过滤: {original_count} → {len(chunks)}")
            if not chunks:
                raise ValueError("文档分块后无有效内容（全部被质量过滤器拦截）")
            total = len(chunks)

            self.update_state(state="PROGRESS", meta={"progress": 30, "step": "embedding", "total_chunks": total})

            all_embeddings = embedding_model._get_text_embeddings(chunks)

            all_ids = [f"{document_id}_chunk_{i}" for i in range(total)]
            all_metadatas = []
            for i, chunk in enumerate(chunks):
                metadata = {
                    "source": os.path.basename(file_path),
                    "chunk_id": i,
                    "total_chunks": total,
                    "document_id": str(document_id),
                    "chunk_strategy": strategy.value,
                }
                if folder_hierarchy:
                    metadata["folder_hierarchy"] = folder_hierarchy
                if parent_id:
                    metadata["parent_id"] = str(parent_id)
                all_metadatas.append(metadata)

            collection.add(
                embeddings=all_embeddings,
                documents=chunks,
                metadatas=all_metadatas,
                ids=all_ids,
            )

            self.update_state(state="PROGRESS", meta={
                "progress": 90, "step": "embedding",
                "current": total, "total_chunks": total,
            })

        # GraphRAG 三元组抽取（分批异步，无上限）
        self.update_state(state="PROGRESS", meta={"progress": 92, "step": "graph_extraction"})
        try:
            from app.services.rag.graph_rag import NEO4J_ENABLED, extract_triples, store_triples
            if NEO4J_ENABLED:
                import asyncio
                loop = asyncio.new_event_loop()
                all_triples = []
                graph_texts = [pc.parent_content for pc in pc_chunks] if pc_chunks else chunks
                BATCH_SIZE = 10

                for batch_start in range(0, len(graph_texts), BATCH_SIZE):
                    batch = graph_texts[batch_start:batch_start + BATCH_SIZE]
                    coros = [
                        extract_triples(
                            text,
                            chunk_id=f"{document_id}_chunk_{batch_start + i}",
                            document_id=str(document_id),
                        )
                        for i, text in enumerate(batch)
                    ]
                    batch_results = loop.run_until_complete(asyncio.gather(*coros, return_exceptions=True))
                    for result in batch_results:
                        if isinstance(result, list):
                            all_triples.extend(result)

                loop.close()
                if all_triples:
                    store_triples(all_triples, vector_db_id)
                logger.info(f"GraphRAG 抽取完成: {len(all_triples)} 条三元组 from {len(graph_texts)} chunks")
        except Exception as graph_err:
            logger.warning(f"Celery 任务 GraphRAG 抽取失败: {graph_err}")

        from app.services.rag.retrieval import invalidate_bm25_cache
        invalidate_bm25_cache(vector_db_id)

        self.update_state(state="PROGRESS", meta={"progress": 100, "step": "done"})
        logger.info(f"[Celery] 文档入库完成: document_id={document_id}")

        return {"document_id": document_id, "status": "success"}

    except Exception as exc:
        logger.error(f"[Celery] 文档入库失败: {exc}", exc_info=True)
        try:
            self.retry(exc=exc, countdown=10 * (self.request.retries + 1))
        except self.MaxRetriesExceededError:
            return {"document_id": document_id, "status": "failed", "error": str(exc)}
