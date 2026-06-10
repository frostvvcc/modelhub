"""
异步向量数据库 Service
处理向量数据库相关的业务逻辑
"""
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict, Any
from app.utils.optimized_chromadb import get_chromadb_client
from app.utils.EmbbedingModel import ChatEmbeddings
from app.models.vector_db import VectorDb
from app.models.document import Document
from app.models.model_info import ModelInfo
from app.models.user import User
from app.mappers.vector_mapper import AsyncVectorMapper
from app.mappers.model_mapper import AsyncModelMapper
from app.mappers.organization_mapper import AsyncOrganizationMapper
from app.services.permission_service import AsyncPermissionService
from app.services.simple_permission_service import SimplePermissionService
from app.utils.async_db import AsyncDB
from app.config import settings
from app.utils.logger_config import get_logger
from app.utils.error_handler import (
    NotFoundError,
    ValidationError,
    InternalServerError,
    UnauthorizedError
)
import chromadb.errors
import os
import uuid
import re
import json
import shutil
import asyncio
from pathlib import Path
from datetime import datetime
from app.utils.archive_utils import is_archive_file, extract_archive, organize_files_by_structure, is_image_file
from app.utils.ocr_utils import process_image_with_ocr

logger = get_logger(__name__)

# ---- 元数据提取 ----

_metadata_mapping_cache = None
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_METADATA_MAPPING_PATH = _PROJECT_ROOT / "scripts" / "metadata_mapping.json"
if not _METADATA_MAPPING_PATH.exists() and ".claude/worktrees" in str(_PROJECT_ROOT):
    _ORIGINAL_ROOT = Path(str(_PROJECT_ROOT).split(".claude/worktrees")[0].rstrip("/"))
    _METADATA_MAPPING_PATH = _ORIGINAL_ROOT / "backend" / "scripts" / "metadata_mapping.json"

_YEAR_IN_TEXT_RE = re.compile(r'(\d{4})\s*年\s*\d{1,2}\s*月')
_DATE_IN_TEXT_RE = re.compile(r'(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})')


def _load_metadata_mapping() -> dict:
    global _metadata_mapping_cache
    if _metadata_mapping_cache is not None:
        return _metadata_mapping_cache
    if _METADATA_MAPPING_PATH.exists():
        try:
            _metadata_mapping_cache = json.loads(_METADATA_MAPPING_PATH.read_text(encoding="utf-8"))
            logger.info(f"加载元数据映射: {_METADATA_MAPPING_PATH}")
        except Exception as e:
            logger.warning(f"元数据映射加载失败: {e}")
            _metadata_mapping_cache = {}
    else:
        _metadata_mapping_cache = {}
    return _metadata_mapping_cache


def _extract_document_metadata(file_path: str, text_content: str = "") -> dict:
    """
    从文件路径和内容中提取结构化元数据（院系、分类、日期）。
    优先使用 metadata_mapping.json，其次从文件路径和正文推断。
    """
    result = {}
    filename = os.path.basename(file_path)

    # 1. 尝试从 metadata_mapping.json 查找
    mapping = _load_metadata_mapping()
    file_meta = mapping.get("file_metadata", {})
    for key, meta in file_meta.items():
        if meta.get("filename") == filename:
            result["department"] = meta.get("department", "")
            result["category"] = meta.get("category", "")
            break

    # 2. 从文件路径推断（如果路径包含院系/分类目录结构）
    if not result.get("department"):
        path_parts = Path(file_path).parts
        for i, part in enumerate(path_parts):
            if part == "output" and i + 2 < len(path_parts):
                result["department"] = path_parts[i + 1]
                result["category"] = path_parts[i + 2]
                break

    # 3. 从 URL 元数据查找发布日期
    url_meta = mapping.get("url_metadata", {})
    for url, meta in url_meta.items():
        dept_from_url = meta.get("department_from_url", "")
        if dept_from_url and result.get("department") and dept_from_url == result["department"]:
            if meta.get("publish_date"):
                result["publish_date"] = meta["publish_date"]
                result["publish_year"] = meta["publish_date"][:4]
                break

    # 4. 从正文内容提取年份（fallback）
    if not result.get("publish_year") and text_content:
        date_match = _DATE_IN_TEXT_RE.search(text_content[:500])
        if date_match:
            year = date_match.group(1)
            if 1990 <= int(year) <= 2030:
                result["publish_year"] = year
                result["publish_date"] = f"{year}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
        else:
            year_match = _YEAR_IN_TEXT_RE.search(text_content[:500])
            if year_match:
                year = year_match.group(1)
                if 1990 <= int(year) <= 2030:
                    result["publish_year"] = year

    return result

MAX_RETRIES = 5
RETRY_DELAY = 2
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
BASE_DOCS_DIR = Path("data/knowledge_sources")
OFFICIAL_VECTOR_DB_NAMES = {
    "山东科技大学官方资料总库",
    "默认智能对话知识库",
}
LAYERED_RAG_FALLBACK_THRESHOLD = float(os.getenv("RAG_FALLBACK_THRESHOLD", "0.40"))
LAYERED_RAG_MAX_VECTOR_DBS = int(os.getenv("RAG_MAX_VECTOR_DBS", "2"))
LAYERED_RAG_MAX_CONTEXTS = int(os.getenv("RAG_MAX_CONTEXTS", "5"))
RAG_USE_ENHANCED = os.getenv("RAG_USE_ENHANCED", "true").lower() in ("true", "1", "yes")
RAG_USE_REWRITE = os.getenv("RAG_USE_REWRITE", "true").lower() in ("true", "1", "yes")
RAG_USE_RERANK = os.getenv("RAG_USE_RERANK", "true").lower() in ("true", "1", "yes")
RAG_USE_HYDE = os.getenv("RAG_USE_HYDE", "false").lower() in ("true", "1", "yes")
CHAT_ATTACHMENT_VECTOR_DB_PREFIX = "会话附件库"
CHAT_ATTACHMENT_MAX_FILE_SIZE = 20 * 1024 * 1024
CHAT_ATTACHMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".txt", ".md", ".csv",
    ".xlsx", ".xls", ".pptx", ".ppt",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp",
    ".zip", ".tar", ".gz", ".tgz",
}


class AsyncVectorService:
    """异步向量数据库服务类"""
    
    @staticmethod
    async def create_chroma_collection(vector_db_id: int) -> bool:
        """创建 ChromaDB 集合（异步，带重试）"""
        from app.utils.retry import async_retry
        
        client = get_chromadb_client()
        if not client:
            logger.error("无法获取 ChromaDB 客户端")
            return False
        
        collection_name = f"vector_db_{vector_db_id}"
        
        @async_retry(
            max_attempts=MAX_RETRIES,
            delay=RETRY_DELAY,
            exceptions=(Exception,)
        )
        async def _create():
            try:
                await asyncio.to_thread(
                    client.create_collection,
                    name=collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info(f"成功创建集合: {collection_name}")
                return True
            except chromadb.errors.UniqueConstraintError:
                logger.info(f"集合已存在: {collection_name}")
                return True
        
        try:
            return await _create()
        except Exception as e:
            logger.error(f"创建集合最终失败: {collection_name}, 错误: {e}")
            return False
    
    @staticmethod
    async def get_chroma_collection(vector_db_id: int):
        """获取 ChromaDB 集合（异步）"""
        client = get_chromadb_client()
        if not client:
            return None
        
        collection_name = f"vector_db_{vector_db_id}"
        try:
            # 在后台线程执行同步操作
            collection = await asyncio.to_thread(client.get_collection, name=collection_name)
            return collection
        except Exception as e:
            logger.error(f"获取集合失败: {e}")
            return None
    
    @staticmethod
    async def ensure_collection_exists(vector_db_id: int) -> bool:
        """确保 ChromaDB 集合存在（异步）"""
        collection = await AsyncVectorService.get_chroma_collection(vector_db_id)
        if collection:
            return True
        return await AsyncVectorService.create_chroma_collection(vector_db_id)
    
    @staticmethod
    async def get_vector_db(
        session: AsyncSession,
        vector_db_id: int,
        user_id: Optional[int] = None
    ) -> Optional[Dict]:
        """
        获取向量数据库详情（异步，支持权限检查）
        
        Raises:
            NotFoundError: 向量数据库不存在
            UnauthorizedError: 无权限访问
            InternalServerError: 获取失败
        """
        logger.debug(f"获取向量数据库详情: vector_db_id={vector_db_id}, user_id={user_id}")
        try:
            vector_db = await AsyncVectorMapper.get_vector_db(session, vector_db_id)
            if not vector_db:
                logger.warning(f"获取向量数据库失败: 不存在 - vector_db_id={vector_db_id}")
                raise NotFoundError(f"向量数据库不存在: {vector_db_id}")
            
            # 权限检查
            if user_id:
                has_access = await AsyncVectorService.check_vector_db_access(
                    session, user_id, vector_db_id
                )
                if not has_access:
                    logger.warning(f"获取向量数据库失败: 无权限 - user_id={user_id}, vector_db_id={vector_db_id}")
                    raise UnauthorizedError("无权限访问该向量数据库")
            
            # 获取文档列表
            documents = await AsyncDB.filter_by(session, Document, vector_db_id=vector_db_id)
            
            logger.debug(f"成功获取向量数据库详情: vector_db_id={vector_db_id}")
            return vector_db.to_dict(
                include_documents=True,
                documents_list=list(documents)
            )
        except NotFoundError:
            raise
        except UnauthorizedError:
            raise
        except Exception as e:
            logger.error(f"获取向量数据库失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"获取向量数据库失败: {str(e)}")
    
    @staticmethod
    async def check_vector_db_access(
        session: AsyncSession,
        user_id: int,
        vector_db_id: int
    ) -> bool:
        """检查用户是否有权限访问向量数据库"""
        return await SimplePermissionService.check_vector_db_access(
            session, user_id, vector_db_id
        )

    @staticmethod
    async def get_accessible_vector_dbs(
        session: AsyncSession,
        user_id: int,
        school_id: Optional[int] = None,
        organization_id: Optional[int] = None
    ) -> List[Dict]:
        """获取用户可访问的向量数据库列表"""
        return await SimplePermissionService.get_accessible_vector_dbs(session, user_id)
    
    @staticmethod
    async def upload_file(
        session: AsyncSession,
        vector_db_id: int,
        file: Any,
        user_id: int,
        describe: str = "",
        parent_id: Optional[int] = None,
        chunk_strategy: str = "markdown",
        chunk_size: int = 800,
        chunk_overlap: int = 150,
    ) -> Optional[int]:
        """上传文件到向量数据库（异步）"""
        from app.utils.performance import async_timer
        
        async with async_timer(f"文件上传 vector_db_{vector_db_id}"):
            document = None
            try:
                # 确保集合存在
                await AsyncVectorService.ensure_collection_exists(vector_db_id)
                
                # 获取向量数据库
                vector_db = await AsyncVectorMapper.get_vector_db(session, vector_db_id)
                if not vector_db:
                    raise NotFoundError(f"向量数据库不存在: {vector_db_id}")
                
                # 保存文件（异步）
                from app.utils.async_file_utils import save_uploaded_file_async
                file_path = await save_uploaded_file_async(
                    file,
                    str(BASE_DOCS_DIR / f"vector_db_{vector_db_id}")
                )
                
                if not file_path:
                    raise ValidationError("文件保存失败")
                
                full_path = BASE_DOCS_DIR / f"vector_db_{vector_db_id}" / file_path
                
                # 验证父文件夹（如果指定）
                folder_path = None
                if parent_id:
                    parent = await AsyncDB.get_by_id(session, Document, parent_id)
                    if not parent:
                        raise NotFoundError(f"父文件夹不存在: {parent_id}")
                    if not parent.is_folder:
                        raise ValidationError("父项不是文件夹")
                    if parent.vector_db_id != vector_db_id:
                        raise ValidationError("父文件夹不属于该向量数据库")
                    if parent.folder_path:
                        folder_path = f"{parent.folder_path}/{parent.id}"
                    else:
                        folder_path = str(parent.id)
                
                # 创建文档记录
                filename = file.filename if hasattr(file, 'filename') else file_path
                document = Document(
                    vector_db_id=vector_db_id,
                    user_id=user_id,
                    name=filename,
                    original_name=filename,
                    type=filename.split('.')[-1] if '.' in filename else 'unknown',
                    size=file.size if hasattr(file, 'size') else 0,
                    save_path=str(full_path),
                    describe=describe,
                    status="processing",
                    parent_id=parent_id,
                    is_folder=False,
                    folder_path=folder_path
                )
                document = await AsyncDB.create(session, document)
                await AsyncDB.commit(session)
                
                # 处理文件并添加到向量数据库
                # 优先走 Celery 异步任务队列（如果可用），否则降级为同步处理
                use_celery = os.getenv("USE_CELERY", "false").lower() in ("true", "1", "yes")
                if use_celery:
                    try:
                        from app.tasks.document_tasks import process_document_task
                        task = process_document_task.delay(
                            vector_db_id, str(full_path), document.id,
                            folder_path, parent_id,
                            chunk_strategy, chunk_size, chunk_overlap,
                        )
                        logger.info(f"文档入库任务已提交 Celery: task_id={task.id}, document_id={document.id}")
                        document.status = "processing"
                        document.error_message = f"celery_task_id:{task.id}"
                        document = await AsyncDB.update(session, document)
                        await AsyncDB.commit(session)
                        return document.id
                    except Exception as celery_err:
                        logger.warning(f"Celery 提交失败，降级为同步处理: {celery_err}")

                await asyncio.to_thread(
                    AsyncVectorService._process_and_add_file,
                    vector_db_id,
                    str(full_path),
                    document.id,
                    folder_path,
                    parent_id,
                    chunk_strategy,
                    chunk_size,
                    chunk_overlap,
                )

                document.status = "success"
                document.error_message = None
                document = await AsyncDB.update(session, document)
                await AsyncDB.commit(session)
                
                return document.id
            except (NotFoundError, ValidationError):
                await AsyncDB.rollback(session)
                raise
            except Exception as e:
                logger.error(f"文件上传失败: {str(e)}", exc_info=True)
                await AsyncDB.rollback(session)
                if document is not None:
                    try:
                        document.status = "failed"
                        document.error_message = str(e)[:2000]
                        await AsyncDB.update(session, document)
                        await AsyncDB.commit(session)
                    except Exception as status_exc:
                        logger.warning(f"更新文档失败状态失败: document_id={getattr(document, 'id', None)}, 错误: {status_exc}")
                raise InternalServerError(f"文件上传失败: {str(e)}")
    
    @staticmethod
    def _process_and_add_file(
        vector_db_id: int,
        file_path: str,
        document_id: int,
        folder_hierarchy: Optional[str] = None,
        parent_id: Optional[int] = None,
        chunk_strategy: str = "markdown",
        chunk_size: int = 800,
        chunk_overlap: int = 150,
    ):
        """
        处理文件并添加到向量数据库（同步方法，在后台线程执行）

        Args:
            vector_db_id: 向量数据库ID
            file_path: 文件路径
            document_id: 文档ID
            folder_hierarchy: 文件夹层级路径 (如: "课程设计/第一章/1.1节")
            parent_id: 父文件夹ID
        """
        ocr_text_path = None
        try:
            # 获取向量存储（通过可插拔抽象层，支持 ChromaDB / Milvus 切换）
            from app.utils.vector_store import get_vector_store
            store = get_vector_store()
            collection_name = f"vector_db_{vector_db_id}"
            # 保持向后兼容：如果是 ChromaDB，直接拿 collection 对象
            collection = store.get_collection(collection_name)

            # 检查是否为图片文件，如果是则进行OCR处理
            actual_file_path = file_path
            if is_image_file(file_path):
                logger.info(f"检测到图片文件，开始OCR识别: {file_path}")
                ocr_text_path = process_image_with_ocr(file_path, output_dir=os.path.dirname(file_path))
                if ocr_text_path and os.path.exists(ocr_text_path):
                    actual_file_path = ocr_text_path
                    logger.info(f"OCR识别完成，使用文本文件: {ocr_text_path}")
                else:
                    raise RuntimeError(f"OCR识别失败，无法提取图片文字: {file_path}")

            from app.services.rag.document_parser import extract_text, clean_web_text, is_worth_indexing
            text_content = extract_text(actual_file_path)

            if not text_content or not text_content.strip():
                raise RuntimeError(f"文件内容为空，无法解析文件: {os.path.basename(file_path)}")

            text_content = clean_web_text(text_content)
            if not is_worth_indexing(text_content):
                raise RuntimeError(f"文件清洗后有效内容不足，跳过入库: {os.path.basename(file_path)}")

            # 获取嵌入模型（使用配置）
            from app.config import settings
            embedding_model = ChatEmbeddings(
                model=settings.embedding_model,
                base_url=settings.embedding_base_url,
                api_key=settings.embedding_api_key
            )

            # 分割文本为块（使用 rag/chunking 模块）
            from app.services.rag.chunking import split_text_into_chunks, ChunkStrategy, split_parent_child, split_contextual
            try:
                strategy = ChunkStrategy(chunk_strategy)
            except ValueError:
                logger.warning("未知切块策略 %s，已降级为 fixed", chunk_strategy)
                strategy = ChunkStrategy.FIXED
            safe_chunk_size = max(100, min(int(chunk_size or 800), 4000))
            safe_overlap = max(0, min(int(chunk_overlap or 150), safe_chunk_size - 1))

            # 公共 metadata 字段
            base_meta = {
                'source': os.path.basename(actual_file_path),
                'document_id': str(document_id),
                'chunk_strategy': strategy.value,
                'chunk_size': safe_chunk_size,
                'chunk_overlap': safe_overlap,
            }
            if folder_hierarchy:
                base_meta['folder_hierarchy'] = folder_hierarchy
            if parent_id:
                base_meta['parent_id'] = str(parent_id)
            if is_image_file(file_path):
                base_meta['source_type'] = 'image_ocr'
                base_meta['original_image'] = os.path.basename(file_path)

            # 结构化元数据：从 metadata_mapping.json 或文件路径提取
            doc_metadata = _extract_document_metadata(actual_file_path, text_content)
            if doc_metadata.get('department'):
                base_meta['department'] = doc_metadata['department']
            if doc_metadata.get('category'):
                base_meta['category'] = doc_metadata['category']
            if doc_metadata.get('publish_date'):
                base_meta['publish_date'] = doc_metadata['publish_date']
            if doc_metadata.get('publish_year'):
                base_meta['publish_year'] = doc_metadata['publish_year']

            chunks = []
            pc_chunks = []

            if strategy == ChunkStrategy.PARENT_CHILD:
                child_size = max(100, safe_chunk_size // 4)
                pc_chunks = split_parent_child(
                    text_content,
                    parent_size=safe_chunk_size,
                    child_size=child_size,
                )
                texts_to_embed = [pc.child_content for pc in pc_chunks]
                all_embeddings = embedding_model._get_text_embeddings(texts_to_embed)

                all_ids = [f"{document_id}_chunk_{i}" for i in range(len(pc_chunks))]
                all_documents = texts_to_embed
                all_metadatas = [
                    {
                        **base_meta,
                        'chunk_id': i,
                        'total_chunks': len(pc_chunks),
                        'parent_content': pc.parent_content,
                        'parent_index': pc.parent_index,
                        'child_index': pc.child_index,
                        'is_child_chunk': True,
                    }
                    for i, pc in enumerate(pc_chunks)
                ]
                store.add(collection_name, all_ids, all_embeddings, all_documents, all_metadatas)
            elif strategy == ChunkStrategy.SEMANTIC:
                from app.services.rag.chunking import split_semantic
                chunks = split_semantic(
                    text_content,
                    embedding_fn=embedding_model._get_text_embeddings,
                    max_chunk_size=safe_chunk_size,
                )
                all_embeddings = embedding_model._get_text_embeddings(chunks)
                all_ids = [f"{document_id}_chunk_{i}" for i in range(len(chunks))]
                all_metadatas = [
                    {**base_meta, 'chunk_id': i, 'total_chunks': len(chunks)}
                    for i in range(len(chunks))
                ]
                store.add(collection_name, all_ids, all_embeddings, chunks, all_metadatas)
            elif strategy == ChunkStrategy.CONTEXTUAL:
                import asyncio as _ctx_aio
                _ctx_loop = _ctx_aio.new_event_loop()
                ctx_chunks = _ctx_loop.run_until_complete(split_contextual(
                    text_content,
                    chunk_size=safe_chunk_size,
                    overlap=safe_overlap,
                ))
                _ctx_loop.close()
                texts_to_embed = [c.contextualized_content for c in ctx_chunks]
                all_embeddings = embedding_model._get_text_embeddings(texts_to_embed)
                all_ids = [f"{document_id}_chunk_{i}" for i in range(len(ctx_chunks))]
                all_documents = [c.original_content for c in ctx_chunks]
                all_metadatas = [
                    {
                        **base_meta,
                        'chunk_id': i,
                        'total_chunks': len(ctx_chunks),
                        'context_prefix': c.context_prefix,
                        'contextualized_content': c.contextualized_content[:500],
                    }
                    for i, c in enumerate(ctx_chunks)
                ]
                store.add(collection_name, all_ids, all_embeddings, all_documents, all_metadatas)
                chunks = all_documents
            else:
                chunks = split_text_into_chunks(
                    text_content,
                    strategy=strategy,
                    chunk_size=safe_chunk_size,
                    overlap=safe_overlap,
                )
                from app.services.rag.document_parser import is_quality_chunk
                original_count = len(chunks)
                chunks = [c for c in chunks if is_quality_chunk(c)]
                if len(chunks) < original_count:
                    logger.info(f"Chunk 质量过滤: {original_count} → {len(chunks)} (过滤 {original_count - len(chunks)} 个低质 chunk)")
                if not chunks:
                    raise ValueError("文档分块后无有效内容（全部被质量过滤器拦截）")
                all_embeddings = embedding_model._get_text_embeddings(chunks)
                all_ids = [f"{document_id}_chunk_{i}" for i in range(len(chunks))]
                all_metadatas = [
                    {**base_meta, 'chunk_id': i, 'total_chunks': len(chunks)}
                    for i in range(len(chunks))
                ]
                store.add(collection_name, all_ids, all_embeddings, chunks, all_metadatas)

            # Elasticsearch 同步索引（ES 可用时写入，不可用时跳过）
            try:
                from app.services.rag.es_retrieval import ES_ENABLED, index_chunks as es_index_chunks
                if ES_ENABLED:
                    es_chunks = [
                        {
                            "chunk_id": f"{document_id}_chunk_{i}",
                            "content": (pc_chunks[i].child_content if pc_chunks else chunks[i]) if i < len(pc_chunks or chunks) else "",
                            "source": base_meta.get("source", ""),
                            "document_id": str(document_id),
                            "department": base_meta.get("department", ""),
                            "category": base_meta.get("category", ""),
                            "publish_date": base_meta.get("publish_date", ""),
                            "publish_year": base_meta.get("publish_year", ""),
                        }
                        for i in range(len(pc_chunks) if pc_chunks else len(chunks))
                    ]
                    import asyncio as _es_aio
                    _es_loop = _es_aio.new_event_loop()
                    _es_loop.run_until_complete(es_index_chunks(vector_db_id, es_chunks))
                    _es_loop.close()
            except Exception as es_err:
                logger.warning(f"Elasticsearch 索引写入失败（不影响主流程）: {es_err}")

            # GraphRAG：从入库的 chunk 中抽取三元组写入 Neo4j
            try:
                from app.services.rag.graph_rag import NEO4J_ENABLED, extract_triples, store_triples
                if NEO4J_ENABLED:
                    import asyncio as _aio
                    loop = _aio.new_event_loop()
                    all_triples = []
                    graph_texts = ([pc.parent_content for pc in pc_chunks] if pc_chunks else chunks)[:50]
                    for idx, chunk_text in enumerate(graph_texts):
                        if chunk_text:
                            triples = loop.run_until_complete(extract_triples(
                                chunk_text, chunk_id=f"{document_id}_chunk_{idx}", document_id=str(document_id),
                            ))
                            all_triples.extend(triples)
                    loop.close()
                    if all_triples:
                        store_triples(all_triples, vector_db_id)
            except Exception as graph_err:
                logger.warning(f"GraphRAG 三元组抽取/存储失败（不影响向量入库）: {graph_err}")

            # 使 BM25 索引缓存失效（新文档入库后需重建）
            from app.services.rag.retrieval import invalidate_bm25_cache
            invalidate_bm25_cache(vector_db_id)
            logger.info(f"文件处理完成: {file_path}")
        except Exception as e:
            logger.error(f"处理文件失败: {e}", exc_info=True)
            raise
        finally:
            # 清理OCR临时文件（如果存在且不是原始文件）
            if ocr_text_path and ocr_text_path != file_path and os.path.exists(ocr_text_path):
                try:
                    # 注意：这里不删除OCR文本文件，因为它可能被用于后续处理
                    # 如果需要清理，可以在文档处理完成后统一清理
                    pass
                except Exception as e:
                    logger.warning(f"清理OCR临时文件失败: {ocr_text_path}, 错误: {e}")

    @staticmethod
    async def delete_vector_db(
        session: AsyncSession,
        vector_db_id: int
    ) -> bool:
        """删除知识库、其文档、本地文件和 Chroma 集合。"""
        logger.info(f"删除向量数据库: vector_db_id={vector_db_id}")
        try:
            vector_db = await AsyncDB.get_by_id(session, VectorDb, vector_db_id)
            if not vector_db:
                return False

            from app.utils.async_file_utils import delete_file_async

            documents = await AsyncDB.filter_by(session, Document, vector_db_id=vector_db_id)
            collection = None
            try:
                collection = get_chromadb_client().get_collection(f"vector_db_{vector_db_id}")
            except Exception as e:
                logger.warning(f"获取向量集合失败，继续删除数据库记录: vector_db_id={vector_db_id}, 错误: {e}")

            def delete_order(item: Document) -> tuple:
                folder_depth = len([part for part in (item.folder_path or "").split("/") if part])
                return (1 if item.is_folder else 0, -folder_depth, -item.id)

            for document in sorted(documents, key=delete_order):
                if not document.is_folder:
                    if collection:
                        try:
                            await asyncio.to_thread(
                                collection.delete,
                                where={"document_id": str(document.id)}
                            )
                        except Exception as e:
                            logger.warning(f"删除文档向量失败: document_id={document.id}, 错误: {e}")
                    if document.save_path:
                        await delete_file_async(document.save_path)
                await AsyncDB.delete(session, document)

            try:
                await asyncio.to_thread(
                    get_chromadb_client().delete_collection,
                    f"vector_db_{vector_db_id}"
                )
            except Exception as e:
                logger.warning(f"删除 Chroma 集合失败: vector_db_id={vector_db_id}, 错误: {e}")

            vector_dir = BASE_DOCS_DIR / f"vector_db_{vector_db_id}"
            if vector_dir.exists():
                await asyncio.to_thread(shutil.rmtree, vector_dir, ignore_errors=True)

            try:
                from app.services.rag.retrieval import invalidate_bm25_cache
                invalidate_bm25_cache(vector_db_id)
            except Exception as e:
                logger.warning(f"BM25 缓存失效失败: vector_db_id={vector_db_id}, 错误: {e}")

            AsyncVectorService.invalidate_kb_embedding_cache(vector_db_id)

            try:
                from app.services.rag.es_retrieval import delete_index as es_delete_index
                await es_delete_index(vector_db_id)
            except Exception as e:
                logger.warning(f"ES 索引删除失败: vector_db_id={vector_db_id}, 错误: {e}")

            try:
                from app.services.rag.graph_rag import NEO4J_ENABLED, _get_driver
                if NEO4J_ENABLED and _get_driver():
                    def _delete_kb_graph():
                        driver = _get_driver()
                        with driver.session() as neo_session:
                            neo_session.run(
                                "MATCH ()-[r:RELATION {kb_id: $kb_id}]->() DELETE r",
                                kb_id=str(vector_db_id),
                            )
                            neo_session.run(
                                "MATCH (n:Entity {kb_id: $kb_id}) DELETE n",
                                kb_id=str(vector_db_id),
                            )
                    await asyncio.to_thread(_delete_kb_graph)
                    logger.info(f"Neo4j 图谱已清理: vector_db_id={vector_db_id}")
            except Exception as e:
                logger.warning(f"Neo4j 图谱清理失败: vector_db_id={vector_db_id}, 错误: {e}")

            from app.models.teaching_space import TeachingSpaceResource
            from sqlalchemy import delete as sa_delete
            await session.execute(
                sa_delete(TeachingSpaceResource).where(
                    TeachingSpaceResource.resource_type == "vector_db",
                    TeachingSpaceResource.resource_id == vector_db_id
                )
            )

            await AsyncDB.delete(session, vector_db)
            await AsyncDB.commit(session)
            logger.info(f"成功删除向量数据库: vector_db_id={vector_db_id}")
            return True
        except Exception as e:
            logger.error(f"删除向量数据库失败: {str(e)}", exc_info=True)
            await AsyncDB.rollback(session)
            raise InternalServerError(f"删除向量数据库失败: {str(e)}")

    @staticmethod
    async def delete_file(
        session: AsyncSession,
        document_id: int
    ) -> bool:
        """
        删除文档（异步）
        
        Raises:
            NotFoundError: 文档不存在
            InternalServerError: 删除失败
        """
        logger.info(f"删除文档: document_id={document_id}")
        try:
            document = await AsyncDB.get_by_id(session, Document, document_id)
            if not document:
                logger.warning(f"删除文档失败: 文档不存在 - document_id={document_id}")
                raise NotFoundError(f"文档不存在: {document_id}")
            
            # 如果是文件夹，检查是否有子项
            if document.is_folder:
                from sqlalchemy import select
                children = await session.execute(
                    select(Document).where(Document.parent_id == document_id)
                )
                children_list = children.scalars().all()
                if children_list:
                    raise ValidationError("文件夹不为空，无法删除")
            
            # 删除文件（异步）
            from app.utils.async_file_utils import delete_file_async
            if document.save_path:
                await delete_file_async(document.save_path)

            # 从 ChromaDB 删除该文档对应的所有 chunk，避免数据库记录删除后旧向量仍被检索到。
            if not document.is_folder:
                try:
                    collection = get_chromadb_client().get_collection(
                        f"vector_db_{document.vector_db_id}"
                    )
                    await asyncio.to_thread(
                        collection.delete,
                        where={"document_id": str(document.id)}
                    )
                    logger.info(f"从向量数据库删除: document_id={document.id}")
                except Exception as e:
                    logger.warning(f"从向量数据库删除失败，继续删除数据库记录: document_id={document.id}, 错误: {e}")

                try:
                    from app.services.rag.retrieval import invalidate_bm25_cache
                    invalidate_bm25_cache(document.vector_db_id)
                except Exception as e:
                    logger.warning(f"BM25 缓存失效失败: vector_db_id={document.vector_db_id}, 错误: {e}")

                try:
                    from app.services.rag.es_retrieval import delete_by_document as es_delete_doc
                    await es_delete_doc(document.vector_db_id, str(document.id))
                except Exception as e:
                    logger.warning(f"ES 文档索引删除失败: document_id={document.id}, 错误: {e}")

                try:
                    from app.services.rag.graph_rag import NEO4J_ENABLED, delete_graph_by_document
                    if NEO4J_ENABLED:
                        await asyncio.to_thread(delete_graph_by_document, document.vector_db_id, str(document.id))
                except Exception as e:
                    logger.warning(f"Neo4j 图谱删除失败: document_id={document.id}, 错误: {e}")

            # 删除数据库记录
            await AsyncDB.delete(session, document)
            await AsyncDB.commit(session)
            
            logger.info(f"成功删除文档: document_id={document_id}")
            return True
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"删除文件失败: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def _delete_document_vectors(vector_db_id: int, document_id: int) -> None:
        try:
            collection = await asyncio.to_thread(
                get_chromadb_client().get_collection, f"vector_db_{vector_db_id}",
            )
            await asyncio.to_thread(collection.delete, where={"document_id": str(document_id)})
            from app.services.rag.retrieval import invalidate_bm25_cache
            invalidate_bm25_cache(vector_db_id)
        except Exception as e:
            logger.warning(f"删除文档向量失败: vector_db_id={vector_db_id}, document_id={document_id}, 错误: {e}")

    @staticmethod
    async def _iter_document_subtree(session: AsyncSession, document: Document) -> List[Document]:
        """返回文档及其子孙节点，文件夹在前，子项随后。"""
        from sqlalchemy import select

        result = [document]
        if document.is_folder:
            children_result = await session.execute(
                select(Document).where(Document.parent_id == document.id).order_by(Document.is_folder.desc(), Document.name.asc())
            )
            for child in children_result.scalars().all():
                result.extend(await AsyncVectorService._iter_document_subtree(session, child))
        return result

    @staticmethod
    async def archive_document(session: AsyncSession, document_id: int) -> dict:
        """归档文档或文件夹。归档后删除 Chroma 向量，不再参与检索，但保留原文件和数据库记录。"""
        document = await AsyncDB.get_by_id(session, Document, document_id)
        if not document:
            raise NotFoundError(f"文档不存在: {document_id}")

        try:
            subtree = await AsyncVectorService._iter_document_subtree(session, document)
            archived_ids = []
            for item in subtree:
                if not item.is_folder:
                    await AsyncVectorService._delete_document_vectors(item.vector_db_id, item.id)
                item.status = "archived"
                item.archived_at = datetime.now()
                item.error_message = None
                await AsyncDB.update(session, item)
                archived_ids.append(item.id)
            await AsyncDB.commit(session)
            return {"document_id": document_id, "archived_ids": archived_ids, "status": "archived"}
        except Exception as e:
            await AsyncDB.rollback(session)
            logger.error(f"归档文档失败: document_id={document_id}, 错误: {e}", exc_info=True)
            raise InternalServerError(f"归档文档失败: {str(e)}")

    @staticmethod
    async def restore_document(session: AsyncSession, document_id: int) -> dict:
        """恢复归档文档或文件夹。恢复文件时重新解析并写入 Chroma。"""
        document = await AsyncDB.get_by_id(session, Document, document_id)
        if not document:
            raise NotFoundError(f"文档不存在: {document_id}")

        try:
            await AsyncVectorService.ensure_collection_exists(document.vector_db_id)
            subtree = await AsyncVectorService._iter_document_subtree(session, document)
            restored_ids = []
            failed_ids = []

            for item in subtree:
                if item.is_folder:
                    item.status = "success"
                    item.archived_at = None
                    item.error_message = None
                    await AsyncDB.update(session, item)
                    restored_ids.append(item.id)
                    continue

                if not item.save_path or not os.path.exists(item.save_path):
                    item.status = "failed"
                    item.error_message = "原始文件不存在，无法恢复向量"
                    await AsyncDB.update(session, item)
                    failed_ids.append(item.id)
                    continue

                item.status = "processing"
                item.error_message = None
                item.archived_at = None
                await AsyncDB.update(session, item)
                await AsyncDB.commit(session)

                await AsyncVectorService._delete_document_vectors(item.vector_db_id, item.id)
                try:
                    await asyncio.to_thread(
                        AsyncVectorService._process_and_add_file,
                        item.vector_db_id,
                        item.save_path,
                        item.id,
                        item.folder_path,
                        item.parent_id,
                        "markdown",
                        800,
                        150,
                    )
                    item.status = "success"
                    item.error_message = None
                    restored_ids.append(item.id)
                except Exception as exc:
                    item.status = "failed"
                    item.error_message = str(exc)[:2000]
                    failed_ids.append(item.id)
                await AsyncDB.update(session, item)

            await AsyncDB.commit(session)
            return {
                "document_id": document_id,
                "restored_ids": restored_ids,
                "failed_ids": failed_ids,
                "status": "restored" if not failed_ids else "partial_failed",
            }
        except Exception as e:
            await AsyncDB.rollback(session)
            logger.error(f"恢复归档文档失败: document_id={document_id}, 错误: {e}", exc_info=True)
            raise InternalServerError(f"恢复归档文档失败: {str(e)}")

    @staticmethod
    async def delete_folder_recursive(
        session: AsyncSession,
        document_id: int
    ) -> dict:
        """
        递归删除文件夹及其所有子项

        Args:
            session: 数据库会话
            document_id: 文件夹ID

        Returns:
            删除统计信息: {'folders': int, 'files': int}

        Raises:
            NotFoundError: 文档不存在
            ValidationError: 不是文件夹
            InternalServerError: 删除失败
        """
        logger.info(f"递归删除文件夹: document_id={document_id}")

        try:
            document = await AsyncDB.get_by_id(session, Document, document_id)
            if not document:
                raise NotFoundError(f"文档不存在: {document_id}")

            if not document.is_folder:
                raise ValidationError("只能删除文件夹")

            stats = {'folders': 0, 'files': 0}

            # 递归删除函数
            async def delete_recursive(folder_id: int):
                """递归删除子文件夹和文件"""
                from sqlalchemy import select

                # 获取所有子项
                children = await session.execute(
                    select(Document).where(Document.parent_id == folder_id)
                )
                children_list = children.scalars().all()

                for child in children_list:
                    if child.is_folder:
                        # 先递归删除子文件夹的内容
                        await delete_recursive(child.id)
                        # 然后删除子文件夹本身
                        await AsyncDB.delete(session, child)
                        stats['folders'] += 1
                        logger.info(f"删除文件夹: {child.name} (id={child.id})")
                    else:
                        # 删除文件
                        # 1. 删除物理文件
                        if child.save_path:
                            from app.utils.async_file_utils import delete_file_async
                            await delete_file_async(child.save_path)

                        # 2. 从向量数据库删除
                        try:
                            collection = await asyncio.to_thread(
                                get_chromadb_client().get_collection,
                                f"vector_db_{child.vector_db_id}"
                            )
                            await asyncio.to_thread(
                                collection.delete, where={"document_id": str(child.id)}
                            )
                            logger.info(f"从向量数据库删除: document_id={child.id}")
                        except Exception as e:
                            logger.warning(f"从向量数据库删除失败: {e}")

                        # 2b. 清理 ES 索引和 Neo4j 图谱
                        try:
                            from app.services.rag.es_retrieval import delete_by_document as es_delete_doc
                            await es_delete_doc(child.vector_db_id, str(child.id))
                        except Exception:
                            pass
                        try:
                            from app.services.rag.graph_rag import NEO4J_ENABLED, delete_graph_by_document
                            if NEO4J_ENABLED:
                                await asyncio.to_thread(delete_graph_by_document, child.vector_db_id, str(child.id))
                        except Exception:
                            pass

                        # 3. 删除数据库记录
                        await AsyncDB.delete(session, child)
                        stats['files'] += 1
                        logger.info(f"删除文件: {child.name} (id={child.id})")

            # 开始递归删除
            await delete_recursive(document_id)

            # 最后删除文件夹本身
            await AsyncDB.delete(session, document)
            stats['folders'] += 1
            await AsyncDB.commit(session)

            try:
                from app.services.rag.retrieval import invalidate_bm25_cache
                invalidate_bm25_cache(document.vector_db_id)
            except Exception as e:
                logger.warning(f"BM25 缓存失效失败: vector_db_id={document.vector_db_id}, 错误: {e}")

            logger.info(f"递归删除完成: 文件夹={stats['folders']}, 文件={stats['files']}")
            return stats

        except (NotFoundError, ValidationError):
            await AsyncDB.rollback(session)
            raise
        except Exception as e:
            logger.error(f"递归删除失败: {str(e)}", exc_info=True)
            await AsyncDB.rollback(session)
            raise InternalServerError(f"递归删除失败: {str(e)}")
    
    @staticmethod
    async def create_folder(
        session: AsyncSession,
        vector_db_id: int,
        name: str,
        parent_id: Optional[int] = None,
        user_id: int = None
    ) -> dict:
        """
        创建文件夹
        
        Raises:
            ValidationError: 参数错误
            InternalServerError: 创建失败
        """
        logger.info(f"创建文件夹: vector_db_id={vector_db_id}, name={name}, parent_id={parent_id}")
        try:
            # 验证父文件夹是否存在
            if parent_id:
                parent = await AsyncDB.get_by_id(session, Document, parent_id)
                if not parent:
                    raise NotFoundError(f"父文件夹不存在: {parent_id}")
                if not parent.is_folder:
                    raise ValidationError("父项不是文件夹")
                if parent.vector_db_id != vector_db_id:
                    raise ValidationError("父文件夹不属于该向量数据库")
                
                # 计算路径
                if parent.folder_path:
                    folder_path = f"{parent.folder_path}/{parent.id}"
                else:
                    folder_path = str(parent.id)
            else:
                folder_path = None
            
            # 检查同名文件夹是否存在
            from sqlalchemy import select, and_
            existing = await session.execute(
                select(Document).where(
                    and_(
                        Document.vector_db_id == vector_db_id,
                        Document.parent_id == parent_id,
                        Document.name == name,
                        Document.is_folder == True
                    )
                )
            )
            if existing.scalar_one_or_none():
                raise ValidationError("同名文件夹已存在")
            
            # 创建文件夹记录
            folder = Document(
                vector_db_id=vector_db_id,
                user_id=user_id or 1,
                name=name,
                original_name=name,
                type=None,
                size=0,
                save_path=None,
                describe=None,
                parent_id=parent_id,
                is_folder=True,
                folder_path=folder_path
            )
            
            folder = await AsyncDB.create(session, folder)
            await AsyncDB.commit(session)
            
            # 更新路径
            if folder_path:
                new_path = f"{folder_path}/{folder.id}"
            else:
                new_path = str(folder.id)
            
            folder.folder_path = new_path
            await AsyncDB.update(session, folder)
            await AsyncDB.commit(session)
            
            logger.info(f"成功创建文件夹: folder_id={folder.id}")
            return folder.to_dict()
        except (NotFoundError, ValidationError):
            await AsyncDB.rollback(session)
            raise
        except Exception as e:
            logger.error(f"创建文件夹失败: {str(e)}", exc_info=True)
            await AsyncDB.rollback(session)
            raise InternalServerError(f"创建文件夹失败: {str(e)}")
    
    @staticmethod
    async def rename_document(
        session: AsyncSession,
        document_id: int,
        new_name: str
    ) -> dict:
        """
        重命名文档或文件夹
        
        Raises:
            NotFoundError: 文档不存在
            ValidationError: 参数错误
            InternalServerError: 重命名失败
        """
        logger.info(f"重命名文档: document_id={document_id}, new_name={new_name}")
        try:
            document = await AsyncDB.get_by_id(session, Document, document_id)
            if not document:
                raise NotFoundError(f"文档不存在: {document_id}")
            
            # 检查同名项是否存在
            from sqlalchemy import select, and_
            existing = await session.execute(
                select(Document).where(
                    and_(
                        Document.vector_db_id == document.vector_db_id,
                        Document.parent_id == document.parent_id,
                        Document.name == new_name,
                        Document.id != document_id
                    )
                )
            )
            if existing.scalar_one_or_none():
                raise ValidationError("同名项已存在")
            
            # 更新名称
            document.name = new_name
            if not document.is_folder:
                document.original_name = new_name
            
            document = await AsyncDB.update(session, document)
            await AsyncDB.commit(session)
            
            logger.info(f"成功重命名文档: document_id={document_id}")
            return document.to_dict()
        except (NotFoundError, ValidationError):
            await AsyncDB.rollback(session)
            raise
        except Exception as e:
            logger.error(f"重命名文档失败: {str(e)}", exc_info=True)
            await AsyncDB.rollback(session)
            raise InternalServerError(f"重命名文档失败: {str(e)}")
    
    @staticmethod
    async def get_documents_tree(
        session: AsyncSession,
        vector_db_id: int
    ) -> list:
        """
        获取文档树形结构
        
        Returns:
            文档树列表（只包含根节点，子节点在 children 中）
        """
        logger.debug(f"获取文档树: vector_db_id={vector_db_id}")
        try:
            from sqlalchemy import select
            # 获取所有文档
            result = await session.execute(
                select(Document).where(Document.vector_db_id == vector_db_id)
            )
            all_documents = result.scalars().all()
            
            # 构建树形结构
            doc_dict = {}
            root_docs = []
            
            # 第一遍：创建字典
            for doc in all_documents:
                doc_dict[doc.id] = doc.to_dict(include_children=False)
                doc_dict[doc.id]['children'] = []
            
            # 第二遍：构建树
            for doc in all_documents:
                doc_data = doc_dict[doc.id]
                if doc.parent_id:
                    if doc.parent_id in doc_dict:
                        doc_dict[doc.parent_id]['children'].append(doc_data)
                else:
                    root_docs.append(doc_data)
            
            # 排序：文件夹在前，然后按名称排序
            def sort_docs(docs):
                docs.sort(key=lambda x: (not x['is_folder'], x['name']))
                for doc in docs:
                    if doc['children']:
                        sort_docs(doc['children'])
            
            sort_docs(root_docs)
            
            logger.debug(f"成功获取文档树: 共 {len(root_docs)} 个根节点")
            return root_docs
        except Exception as e:
            logger.error(f"获取文档树失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"获取文档树失败: {str(e)}")
    
    @staticmethod
    async def upload_archive(
        session: AsyncSession,
        vector_db_id: int,
        archive_file: Any,
        user_id: int,
        describe: str = "",
        parent_id: Optional[int] = None,
        chunk_strategy: str = "markdown",
        chunk_size: int = 800,
        chunk_overlap: int = 150,
    ) -> List[int]:
        """
        上传并解压压缩包，按结构组织文件
        
        Args:
            session: 数据库会话
            vector_db_id: 向量数据库ID
            archive_file: 压缩包文件
            user_id: 用户ID
            describe: 描述
            parent_id: 父文件夹ID
            
        Returns:
            创建的文档ID列表
        """
        import tempfile
        
        logger.info(f"开始处理压缩包上传: vector_db_id={vector_db_id}")
        
        # 确保集合存在
        await AsyncVectorService.ensure_collection_exists(vector_db_id)
        
        # 获取向量数据库
        vector_db = await AsyncVectorMapper.get_vector_db(session, vector_db_id)
        if not vector_db:
            raise NotFoundError(f"向量数据库不存在: {vector_db_id}")
        
        # 验证父文件夹（如果指定）
        folder_path = None
        if parent_id:
            parent = await AsyncDB.get_by_id(session, Document, parent_id)
            if not parent:
                raise NotFoundError(f"父文件夹不存在: {parent_id}")
            if not parent.is_folder:
                raise ValidationError("父项不是文件夹")
            if parent.vector_db_id != vector_db_id:
                raise ValidationError("父文件夹不属于该向量数据库")
            if parent.folder_path:
                folder_path = f"{parent.folder_path}/{parent.id}"
            else:
                folder_path = str(parent.id)
        
        # 创建临时目录
        temp_dir = tempfile.mkdtemp()
        archive_path = None
        extract_dir = None
        
        try:
            # 保存压缩包到临时目录
            from app.utils.async_file_utils import save_uploaded_file_async
            archive_filename = await save_uploaded_file_async(
                archive_file,
                temp_dir
            )
            
            if not archive_filename:
                raise ValidationError("压缩包保存失败")
            
            archive_path = os.path.join(temp_dir, archive_filename)
            
            # 创建解压目录
            extract_dir = os.path.join(temp_dir, 'extracted')
            os.makedirs(extract_dir, exist_ok=True)
            
            # 解压压缩包（同步执行）
            extracted_files = await asyncio.to_thread(
                extract_archive,
                archive_path,
                extract_dir
            )
            
            if not extracted_files:
                raise ValidationError("压缩包为空或没有支持的文件")
            
            # 组织文件结构
            file_tree = organize_files_by_structure(extracted_files)
            
            # 创建文件夹和文件（递归）
            document_ids = []
            base_dir = BASE_DOCS_DIR / f"vector_db_{vector_db_id}"
            
            # 递归创建文件夹和文件
            async def create_from_tree(tree: dict, current_parent_id: Optional[int], current_path: str = ""):
                for name, item in tree.items():
                    if item['type'] == 'dir':
                        # ⭐ 检查文件夹是否已存在
                        from sqlalchemy import select, and_
                        existing_folder = await session.execute(
                            select(Document).where(
                                and_(
                                    Document.vector_db_id == vector_db_id,
                                    Document.parent_id == current_parent_id,
                                    Document.name == name,
                                    Document.is_folder == True
                                )
                            )
                        )
                        existing = existing_folder.scalar_one_or_none()

                        if existing:
                            # ⭐ 文件夹已存在,跳过创建,直接使用现有文件夹
                            logger.info(f"⏭️ 文件夹已存在,跳过: {name}")
                            folder_id = existing.id
                            document_ids.append(folder_id)

                            # 递归处理子项(在现有文件夹下添加)
                            if item.get('children'):
                                await create_from_tree(item['children'], folder_id, f"{current_path}/{name}")
                        else:
                            # 创建新文件夹
                            folder = await AsyncVectorService.create_folder(
                                session,
                                vector_db_id,
                                name,
                                current_parent_id,
                                user_id
                            )
                            folder_id = folder['id']
                            document_ids.append(folder_id)

                            # 递归处理子项
                            if item.get('children'):
                                await create_from_tree(item['children'], folder_id, f"{current_path}/{name}")
                    else:
                        # 创建文件
                        file_full_path = item['full_path']
                        file_size = item.get('size', 0)

                        # ⭐ 检查文件是否已存在
                        from sqlalchemy import select, and_
                        existing_file = await session.execute(
                            select(Document).where(
                                and_(
                                    Document.vector_db_id == vector_db_id,
                                    Document.parent_id == current_parent_id,
                                    Document.name == name,
                                    Document.is_folder == False
                                )
                            )
                        )
                        existing = existing_file.scalar_one_or_none()

                        if existing:
                            # ⭐ 文件已存在,跳过
                            logger.info(f"⏭️ 文件已存在,跳过: {name}")
                            # 删除临时文件
                            try:
                                os.remove(file_full_path)
                            except:
                                pass
                            continue

                        # 移动文件到目标目录
                        relative_path = f"{current_path}/{name}".lstrip('/')
                        target_path = base_dir / relative_path
                        target_path.parent.mkdir(parents=True, exist_ok=True)

                        shutil.move(file_full_path, str(target_path))

                        # 计算文件的 folder_path
                        file_folder_path = None
                        if current_parent_id:
                            # 获取父文件夹的路径
                            parent_doc = await AsyncDB.get_by_id(session, Document, current_parent_id)
                            if parent_doc and parent_doc.folder_path:
                                file_folder_path = f"{parent_doc.folder_path}/{current_parent_id}"
                            elif parent_doc:
                                file_folder_path = str(current_parent_id)

                        # 创建文档记录
                        document = Document(
                            vector_db_id=vector_db_id,
                            user_id=user_id,
                            name=name,
                            original_name=name,
                            type=Path(name).suffix.lstrip('.') or 'unknown',
                            size=file_size,
                            save_path=str(target_path),
                            describe=describe,
                            status="processing",
                            parent_id=current_parent_id,
                            is_folder=False,
                            folder_path=file_folder_path
                        )
                        document = await AsyncDB.create(session, document)
                        await AsyncDB.commit(session)
                        document_ids.append(document.id)

                        # 处理文件并添加到向量数据库（异步执行）
                        # ⭐ 传递层级路径信息
                        folder_hierarchy = current_path if current_path else None
                        await asyncio.to_thread(
                            AsyncVectorService._process_and_add_file,
                            vector_db_id,
                            str(target_path),
                            document.id,
                            folder_hierarchy,  # 层级路径
                            current_parent_id,  # 父文件夹ID
                            chunk_strategy,
                            chunk_size,
                            chunk_overlap,
                        )

                        document.status = "success"
                        document.error_message = None
                        document = await AsyncDB.update(session, document)
                        await AsyncDB.commit(session)
            
            # 开始创建
            await create_from_tree(file_tree, parent_id)
            
            logger.info(f"成功处理压缩包: 共创建 {len(document_ids)} 个文档/文件夹")
            return document_ids
            
        except (NotFoundError, ValidationError):
            await AsyncDB.rollback(session)
            raise
        except Exception as e:
            logger.error(f"处理压缩包失败: {str(e)}", exc_info=True)
            await AsyncDB.rollback(session)
            raise InternalServerError(f"处理压缩包失败: {str(e)}")
        finally:
            # 清理临时目录
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.warning(f"清理临时目录失败: {str(e)}")
    
    @staticmethod
    async def query_vectors(
        vector_db_id: int,
        query_text: str,
        n_results: int = 5
    ) -> List[Dict]:
        """
        查询向量数据库（异步）。
        委托给 rag/retrieval.VectorRetriever，保持原有返回格式。
        """
        from app.services.rag.retrieval import VectorRetriever
        results = await VectorRetriever.query(vector_db_id, query_text, n_results)
        return [
            {
                "text": r.content,
                "score": r.vector_score,
                "source": r.source or r.metadata.get("source", ""),
                "document_name": r.source or "未知来源",
                "document_id": r.document_id,
                "id": r.chunk_id,
            }
            for r in results
        ]

    @staticmethod
    async def query_vectors_with_hierarchy(
        vector_db_id: int,
        query_text: str,
        n_results: int = 5,
        folder_path: Optional[str] = None,
        parent_id: Optional[int] = None
    ) -> List[Dict]:
        """
        支持层级过滤的向量查询（异步）。
        委托给 rag/retrieval.VectorRetriever，保持原有返回格式。
        """
        from app.services.rag.retrieval import VectorRetriever
        results = await VectorRetriever.query(
            vector_db_id, query_text, n_results, folder_path, parent_id
        )
        return [
            {
                "document": r.content,
                "distance": 1.0 - r.vector_score,
                "id": r.chunk_id,
                "metadata": r.metadata,
            }
            for r in results
        ]

    @staticmethod
    def get_conversation_attachment_vector_db_name(user_id: int, conversation_id: int) -> str:
        return f"{CHAT_ATTACHMENT_VECTOR_DB_PREFIX}-{conversation_id}-用户{user_id}"

    @staticmethod
    async def get_or_create_conversation_attachment_vector_db(
        session: AsyncSession,
        user_id: int,
        conversation_id: int,
        model_config_id: int,
    ) -> VectorDb:
        """为单个对话创建或复用用户私有附件知识库。"""
        from sqlalchemy import select

        name = AsyncVectorService.get_conversation_attachment_vector_db_name(user_id, conversation_id)
        existing = await session.execute(select(VectorDb).where(VectorDb.name == name))
        vector_db = existing.scalars().first()
        if vector_db:
            await AsyncVectorService.ensure_collection_exists(vector_db.id)
            return vector_db

        model_config = await AsyncModelMapper.get_model_config_by_id(session, model_config_id)
        embedding_id = None
        organization_id = None
        school_id = None
        if model_config:
            organization_id = model_config.organization_id
            school_id = getattr(model_config, 'school_id', None)

        if not embedding_id:
            result = await session.execute(
                select(ModelInfo)
                .where(ModelInfo.type == "embedding")
                .order_by(ModelInfo.is_default.desc(), ModelInfo.priority.desc(), ModelInfo.id)
            )
            embedding_model = result.scalars().first()
            if not embedding_model:
                raise ValidationError("未找到可用的嵌入模型，无法创建会话附件知识库")
            embedding_id = embedding_model.id

        vector_db = await AsyncVectorMapper.create_vector_db(
            session,
            user_id=user_id,
            name=name,
            embedding_id=embedding_id,
            describe=f"对话 {conversation_id} 的用户私有上传附件库",
            document_similarity=0.5,
            organization_id=organization_id,
            school_id=school_id,
            scope="private",
            access_level=None,
        )
        await AsyncVectorService.ensure_collection_exists(vector_db.id)
        logger.info("已创建会话附件知识库: conversation_id=%s, vector_db_id=%s", conversation_id, vector_db.id)
        return vector_db

    @staticmethod
    def _validate_chat_attachment(file: Any) -> None:
        filename = getattr(file, "filename", "") or ""
        if not filename:
            raise ValidationError("上传文件缺少文件名")

        ext = Path(filename).suffix.lower()
        if ext not in CHAT_ATTACHMENT_EXTENSIONS:
            raise ValidationError(
                f"不支持的聊天附件类型: {ext or '无扩展名'}，请上传 PDF、Word、Excel、PPT、文本、图片或压缩包"
            )

        size = getattr(file, "size", None)
        if size and size > CHAT_ATTACHMENT_MAX_FILE_SIZE:
            raise ValidationError(f"聊天附件过大: {filename}，单个文件不能超过 20MB")

        if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp"}:
            from app.utils.ocr_utils import PADDLEOCR_AVAILABLE
            if not PADDLEOCR_AVAILABLE:
                raise ValidationError("当前本机未安装 PaddleOCR，聊天图片/扫描件附件暂不能识别；请先上传可复制文字的 PDF、DOCX 或 TXT")

    @staticmethod
    async def upload_conversation_attachments(
        session: AsyncSession,
        user_id: int,
        conversation_id: int,
        model_config_id: int,
        files: Optional[List[Any]],
    ) -> Dict[str, Any]:
        """上传聊天附件到当前对话的私有知识库，并完成向量化。"""
        valid_files = [file for file in (files or []) if getattr(file, "filename", "")]
        if not valid_files:
            return {
                "vector_db_id": None,
                "vector_db_name": None,
                "document_ids": [],
                "filenames": [],
            }

        for file in valid_files:
            AsyncVectorService._validate_chat_attachment(file)

        vector_db = await AsyncVectorService.get_or_create_conversation_attachment_vector_db(
            session,
            user_id,
            conversation_id,
            model_config_id,
        )

        document_ids = []
        filenames = []
        errors = []
        file_contents: Dict[str, str] = {}
        for file in valid_files:
            try:
                await file.seek(0)
                if is_archive_file(file.filename):
                    archive_ids = await AsyncVectorService.upload_archive(
                        session,
                        vector_db_id=vector_db.id,
                        archive_file=file,
                        user_id=user_id,
                        describe=f"对话 {conversation_id} 上传压缩包附件",
                        parent_id=None,
                        chunk_strategy="markdown",
                        chunk_size=800,
                        chunk_overlap=150,
                    )
                    if archive_ids:
                        document_ids.extend(archive_ids)
                        filenames.append(file.filename)
                else:
                    # 先提取文本用于直接注入 prompt
                    try:
                        from app.services.rag.document_parser import extract_text
                        import tempfile, os
                        await file.seek(0)
                        raw = await file.read()
                        suffix = os.path.splitext(file.filename)[1] or ".txt"
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                            tmp.write(raw)
                            tmp_path = tmp.name
                        text = extract_text(tmp_path)
                        os.unlink(tmp_path)
                        if text and text.strip():
                            file_contents[file.filename] = text.strip()
                        await file.seek(0)
                    except Exception:
                        await file.seek(0)

                    doc_id = await AsyncVectorService.upload_file(
                        session,
                        vector_db_id=vector_db.id,
                        file=file,
                        user_id=user_id,
                        describe=f"对话 {conversation_id} 上传附件",
                        parent_id=None,
                        chunk_strategy="markdown",
                        chunk_size=800,
                        chunk_overlap=150,
                    )
                    if doc_id:
                        document_ids.append(doc_id)
                        filenames.append(file.filename)
            except Exception as exc:
                logger.warning("聊天附件上传失败: %s (%s)", getattr(file, "filename", ""), exc)
                errors.append(f"{getattr(file, 'filename', 'unknown')}: {exc}")

        if errors and not document_ids:
            raise ValidationError("聊天附件上传失败：" + "；".join(errors))

        return {
            "vector_db_id": vector_db.id,
            "vector_db_name": vector_db.name,
            "document_ids": document_ids,
            "filenames": filenames,
            "file_contents": file_contents,
            "errors": errors,
        }

    @staticmethod
    async def delete_conversation_attachment_vector_db(
        session: AsyncSession,
        user_id: int,
        conversation_id: int,
    ) -> bool:
        """删除某个对话对应的附件知识库、文件和向量集合。"""
        from sqlalchemy import select
        from app.utils.async_file_utils import delete_file_async

        name = AsyncVectorService.get_conversation_attachment_vector_db_name(user_id, conversation_id)
        result = await session.execute(select(VectorDb).where(VectorDb.name == name, VectorDb.user_id == user_id))
        vector_db = result.scalars().first()
        if not vector_db:
            return False

        documents = await AsyncDB.filter_by(session, Document, vector_db_id=vector_db.id)
        collection = None
        try:
            collection = await asyncio.to_thread(
                get_chromadb_client().get_collection, f"vector_db_{vector_db.id}"
            )
        except Exception as exc:
            logger.warning("获取会话附件向量集合失败，继续删除数据库记录: vector_db_id=%s (%s)", vector_db.id, exc)

        def delete_order(item: Document) -> tuple:
            folder_depth = len([part for part in (item.folder_path or "").split("/") if part])
            # 文件先删，文件夹按深度从深到浅删，避免 parent_id 外键约束残留。
            return (1 if item.is_folder else 0, -folder_depth, -item.id)

        for document in sorted(documents, key=delete_order):
            if not document.is_folder:
                if collection:
                    try:
                        await asyncio.to_thread(
                            collection.delete, where={"document_id": str(document.id)}
                        )
                    except Exception as exc:
                        logger.warning("删除会话附件向量失败: document_id=%s (%s)", document.id, exc)
                if document.save_path:
                    await delete_file_async(document.save_path)
            await AsyncDB.delete(session, document)

        try:
            await asyncio.to_thread(
                get_chromadb_client().delete_collection, f"vector_db_{vector_db.id}"
            )
        except Exception as exc:
            logger.warning("删除会话附件向量集合失败: vector_db_id=%s (%s)", vector_db.id, exc)

        vector_dir = BASE_DOCS_DIR / f"vector_db_{vector_db.id}"
        if vector_dir.exists():
            await asyncio.to_thread(shutil.rmtree, vector_dir, ignore_errors=True)

        await AsyncDB.delete(session, vector_db)
        await AsyncDB.commit(session)
        logger.info("已删除会话附件知识库: conversation_id=%s, vector_db_id=%s", conversation_id, vector_db.id)
        return True

    @staticmethod
    def _empty_rag_result() -> Dict[str, Any]:
        return {
            "contexts": [],
            "sources": [],
            "used_knowledge_base": False,
            "vector_db_id": None,
            "vector_db_ids": [],
            "queried_vector_db_ids": [],
            "retrieval_layers": [],
            "total_results": 0,
            "avg_similarity": 0.0,
            "fallback_used": False,
        }

    @staticmethod
    def _serialize_retrieval_results(
        vector_db: VectorDb,
        layer: str,
        results: list
    ) -> Dict[str, Any]:
        similarity_threshold = float(vector_db.document_similarity or 0.0)

        all_sources = []
        for result in results:
            similarity = max(0.0, min(1.0, result.similarity))
            all_sources.append({
                "id": result.chunk_id,
                "content": result.content,
                "source": result.source,
                "distance": 1.0 - similarity,
                "similarity": similarity,
                "vector_score": result.vector_score,
                "bm25_score": result.bm25_score,
                "final_score": result.score,
                "retrieval_method": result.retrieval_method,
                "document_id": result.document_id,
                "vector_db_id": vector_db.id,
                "vector_db_name": vector_db.name,
                "retrieval_layer": layer,
            })

        if similarity_threshold > 0:
            filtered = [s for s in all_sources if s["similarity"] >= similarity_threshold]
            if len(filtered) < 3:
                filtered = all_sources[:max(3, len(filtered))]
            sources = filtered
        else:
            sources = all_sources

        total_similarity = sum(s["similarity"] for s in sources)
        avg_similarity = total_similarity / len(sources) if sources else 0.0
        return {
            "contexts": [source["content"] for source in sources],
            "sources": sources,
            "used_knowledge_base": bool(sources),
            "vector_db_id": vector_db.id if sources else None,
            "vector_db_ids": [vector_db.id] if sources else [],
            "queried_vector_db_ids": [vector_db.id],
            "retrieval_layers": [layer],
            "total_results": len(sources),
            "avg_similarity": avg_similarity,
            "fallback_used": layer != "primary",
        }

    @staticmethod
    def _merge_layered_rag_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
        merged_sources = []
        seen = set()
        queried_vector_db_ids = []
        retrieval_layers = []

        for result in results:
            for vector_db_id in result.get("queried_vector_db_ids", []):
                if vector_db_id not in queried_vector_db_ids:
                    queried_vector_db_ids.append(vector_db_id)
            for layer in result.get("retrieval_layers", []):
                if layer not in retrieval_layers:
                    retrieval_layers.append(layer)
            for source in result.get("sources", []):
                key = (source.get("vector_db_id"), source.get("id"), source.get("content", "")[:120])
                if key in seen:
                    continue
                seen.add(key)
                merged_sources.append(source)

        merged_sources.sort(
            key=lambda source: max(
                float(source.get("similarity") or 0.0),
                float(source.get("final_score") or 0.0),
            ),
            reverse=True,
        )
        selected_sources = merged_sources[:LAYERED_RAG_MAX_CONTEXTS]
        vector_db_ids = []
        for source in selected_sources:
            vector_db_id = source.get("vector_db_id")
            if vector_db_id is not None and vector_db_id not in vector_db_ids:
                vector_db_ids.append(vector_db_id)

        avg_similarity = (
            sum(float(source.get("similarity") or 0.0) for source in selected_sources) / len(selected_sources)
            if selected_sources else 0.0
        )

        has_result_db_ids = []
        for source in merged_sources:
            vid = source.get("vector_db_id")
            if vid is not None and vid not in has_result_db_ids:
                has_result_db_ids.append(vid)

        return {
            "contexts": [source["content"] for source in selected_sources],
            "sources": selected_sources,
            "used_knowledge_base": bool(selected_sources),
            "vector_db_id": vector_db_ids[0] if vector_db_ids else None,
            "vector_db_ids": vector_db_ids,
            "queried_vector_db_ids": queried_vector_db_ids,
            "has_result_db_ids": has_result_db_ids,
            "retrieval_layers": retrieval_layers,
            "total_results": len(selected_sources),
            "total_found": len(merged_sources),
            "avg_similarity": avg_similarity,
            "fallback_used": any(layer != "primary" for layer in retrieval_layers),
        }


    # ---- Knowledge Router: Query-Aware 知识库路由 ----

    _kb_embedding_cache: Dict[int, tuple] = {}
    _KB_CACHE_TTL = 600

    @staticmethod
    async def _get_kb_embedding(vector_db: "VectorDb") -> List[float]:
        """获取知识库描述的 Embedding（带内存缓存 + TTL）"""
        import time as _time
        cached = AsyncVectorService._kb_embedding_cache.get(vector_db.id)
        if cached and _time.monotonic() - cached[1] < AsyncVectorService._KB_CACHE_TTL:
            return cached[0]
        from app.utils.async_embedding import get_query_embedding_async
        text = f"{vector_db.name} {vector_db.describe or ''}"
        emb = await get_query_embedding_async(text)
        AsyncVectorService._kb_embedding_cache[vector_db.id] = (emb, _time.monotonic())
        return emb

    @staticmethod
    def invalidate_kb_embedding_cache(vector_db_id: int) -> None:
        """知识库改名/删除时清除路由 embedding 缓存"""
        AsyncVectorService._kb_embedding_cache.pop(vector_db_id, None)

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

    @staticmethod
    async def _route_knowledge_bases(
        query: str,
        candidates: List[tuple],
        max_count: int = 3,
    ) -> List[tuple]:
        """Query-Aware Knowledge Router: 按 query 与库描述的语义相似度选择 top-N 库。
        附件库（会话附件库）强制入选，不参与竞争淘汰。"""
        pinned = [(vdb, layer) for vdb, layer in candidates
                  if (vdb.name or "").startswith(CHAT_ATTACHMENT_VECTOR_DB_PREFIX)]
        competitive = [(vdb, layer) for vdb, layer in candidates
                       if not (vdb.name or "").startswith(CHAT_ATTACHMENT_VECTOR_DB_PREFIX)]

        remaining_slots = max(1, max_count - len(pinned))

        if len(competitive) <= remaining_slots:
            selected = pinned + competitive
        else:
            from app.utils.async_embedding import get_query_embedding_async
            query_emb = await get_query_embedding_async(query)

            kb_embeddings = await asyncio.gather(*[
                AsyncVectorService._get_kb_embedding(vdb) for vdb, _ in competitive
            ])
            scored = [
                (AsyncVectorService._cosine_similarity(query_emb, emb), vdb, layer)
                for emb, (vdb, layer) in zip(kb_embeddings, competitive)
            ]

            scored.sort(key=lambda x: x[0], reverse=True)
            selected = pinned + [(vdb, layer) for _, vdb, layer in scored[:remaining_slots]]

        pinned_names = [v.name for v, _ in pinned]
        routed_names = [f"{v.name}({s:.3f})" for s, v, _ in scored[:remaining_slots]] if len(competitive) > remaining_slots else [v.name for v, _ in competitive]
        logger.info(
            f"🔀 [Knowledge Router] {len(candidates)} 库 → {len(selected)} 库 | "
            f"固定: {pinned_names or '无'} | 竞选: {routed_names}"
        )
        return selected

    @staticmethod
    async def _get_layered_vector_db_candidates(
        session: AsyncSession,
        user_id: int,
        primary_vector_db_id: Optional[int],
        extra_vector_db_ids: Optional[List[int]] = None,
        skip_primary: bool = False,
        query: str = "",
    ) -> List[tuple[VectorDb, str]]:
        """按主库、用户私有库、官方总库的顺序生成候选知识库。大量候选时用 Knowledge Router 语义选库。"""
        from sqlalchemy import select, or_

        candidates: List[tuple[VectorDb, str]] = []
        seen_ids = set()

        async def add_candidate(vector_db: Optional[VectorDb], layer: str) -> None:
            if not vector_db or vector_db.id in seen_ids:
                return
            has_access = await AsyncVectorService.check_vector_db_access(session, user_id, vector_db.id)
            if not has_access:
                return
            seen_ids.add(vector_db.id)
            candidates.append((vector_db, layer))

        if not skip_primary and primary_vector_db_id and primary_vector_db_id > 0:
            await add_candidate(await AsyncVectorMapper.get_vector_db(session, primary_vector_db_id), "primary")

        has_user_selected = False
        for vector_db_id in extra_vector_db_ids or []:
            if vector_db_id and vector_db_id > 0:
                vdb = await AsyncVectorMapper.get_vector_db(session, vector_db_id)
                await add_candidate(vdb, "user_selected")
                has_user_selected = True

        if has_user_selected:
            if query and len(candidates) > LAYERED_RAG_MAX_VECTOR_DBS:
                candidates = await AsyncVectorService._route_knowledge_bases(
                    query, candidates, max_count=max(LAYERED_RAG_MAX_VECTOR_DBS, 3),
                )
            return candidates

        # 回退：搜索用户有权访问的所有知识库（私有 + 组织级 + 教学空间）
        from app.services.simple_permission_service import SimplePermissionService
        accessible = await SimplePermissionService.get_accessible_vector_dbs(session, user_id)
        for item in accessible:
            if len(candidates) >= LAYERED_RAG_MAX_VECTOR_DBS:
                break
            vdb = await AsyncVectorMapper.get_vector_db(session, item["id"])
            await add_candidate(vdb, "accessible_fallback")

        return candidates

    @staticmethod
    async def _query_single_vector_db_layer(
        vector_db: VectorDb,
        layer: str,
        message: str,
        n_results: int = 5,
        prepared_query=None,
        skip_rerank: bool = False,
    ) -> Dict[str, Any]:
        """
        查询单个知识库。
        skip_rerank=True 时只做粗排（由调用方合并后统一 rerank）。
        """
        from app.services.rag.retrieval import VectorRetriever

        if not vector_db:
            return AsyncVectorService._empty_rag_result()

        try:
            if prepared_query:
                rag_results = await VectorRetriever.execute_prepared_query(
                    vector_db.id, prepared_query, n_results=n_results,
                    skip_rerank=skip_rerank,
                )
            elif RAG_USE_ENHANCED:
                rag_results = await VectorRetriever.enhanced_query(
                    vector_db.id, message, n_results=n_results,
                    use_rewrite=RAG_USE_REWRITE,
                    use_rerank=RAG_USE_RERANK,
                    use_hyde=RAG_USE_HYDE,
                )
            else:
                rag_results = await VectorRetriever.hybrid_query(
                    vector_db.id, message, n_results=n_results,
                )
            return AsyncVectorService._serialize_retrieval_results(vector_db, layer, rag_results)
        except Exception as exc:
            logger.warning(
                "分层知识库检索失败: vector_db_id=%s, layer=%s (%s)",
                vector_db.id,
                layer,
                exc,
            )
            empty = AsyncVectorService._empty_rag_result()
            empty["queried_vector_db_ids"] = [vector_db.id]
            empty["retrieval_layers"] = [layer]
            return empty
    
    @staticmethod
    async def query_vector_by_model(
        session: AsyncSession,
        model_config_id: int,
        message: str,
        user_id: Optional[int] = None,
        extra_vector_db_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        根据模型配置查询向量数据库（异步）。

        分层检索：
        1. 优先使用调用方指定的 extra_vector_db_ids；
        2. 如果未指定，则查用户私有库；
        3. 最后查官方公开总库兜底。

        Returns:
            包含检索结果和元数据的字典:
            {
                "contexts": List[str],  # 文档内容列表
                "sources": List[Dict],  # 来源信息列表
                "used_knowledge_base": bool,  # 是否使用了知识库
                "vector_db_id": int,  # 向量数据库ID
                "total_results": int,  # 总结果数
                "avg_similarity": float  # 平均相似度
            }
            如果模型配置不存在或没有关联向量数据库则返回空结果
        """
        logger.debug(f"根据模型查询向量: model_config_id={model_config_id}")
        try:
            model_config = await AsyncModelMapper.get_model_config_by_id(session, model_config_id)
            if not model_config:
                logger.debug("根据模型查询向量: 模型配置不存在 - model_config_id=%s", model_config_id)
                return AsyncVectorService._empty_rag_result()

            if not user_id:
                if extra_vector_db_ids:
                    vdb = await AsyncVectorMapper.get_vector_db(session, extra_vector_db_ids[0])
                    if not vdb:
                        return AsyncVectorService._empty_rag_result()
                    prepared = None
                    if RAG_USE_ENHANCED:
                        from app.services.rag.retrieval import VectorRetriever
                        prepared = await VectorRetriever.prepare_query(
                            message, n_results=LAYERED_RAG_MAX_CONTEXTS,
                            use_rewrite=RAG_USE_REWRITE,
                            use_rerank=RAG_USE_RERANK,
                            use_hyde=RAG_USE_HYDE,
                        )
                    return await AsyncVectorService._query_single_vector_db_layer(
                        vdb, "user_selected", message, n_results=LAYERED_RAG_MAX_CONTEXTS,
                        prepared_query=prepared,
                    )
                return AsyncVectorService._empty_rag_result()

            candidates = await AsyncVectorService._get_layered_vector_db_candidates(
                session,
                user_id,
                None,
                extra_vector_db_ids=extra_vector_db_ids,
                skip_primary=True,
                query=message,
            )
            if not candidates:
                logger.debug("根据模型查询向量: 没有可访问的分层知识库 - model_config_id=%s", model_config_id)
                return AsyncVectorService._empty_rag_result()

            # 查询准备：所有 LLM 调用只执行一次（约束提取 + 改写 + HyDE 并行）
            prepared = None
            if RAG_USE_ENHANCED:
                from app.services.rag.retrieval import VectorRetriever
                prepared = await VectorRetriever.prepare_query(
                    message, n_results=LAYERED_RAG_MAX_CONTEXTS,
                    use_rewrite=RAG_USE_REWRITE,
                    use_rerank=RAG_USE_RERANK,
                    use_hyde=RAG_USE_HYDE,
                )

            need_multi_db = len(candidates) > 1
            use_unified_rerank = need_multi_db and RAG_USE_RERANK

            primary_result = None
            fallback_candidates = candidates
            if candidates[0][1] == "primary":
                primary_vector_db, primary_layer = candidates[0]
                primary_result = await AsyncVectorService._query_single_vector_db_layer(
                    primary_vector_db,
                    primary_layer,
                    message,
                    n_results=LAYERED_RAG_MAX_CONTEXTS * 2 if use_unified_rerank else LAYERED_RAG_MAX_CONTEXTS,
                    prepared_query=prepared,
                    skip_rerank=use_unified_rerank,
                )
                fallback_candidates = candidates[1:]
                if not use_unified_rerank and primary_result["used_knowledge_base"] and primary_result["avg_similarity"] >= LAYERED_RAG_FALLBACK_THRESHOLD:
                    logger.info(
                        "✅ [RAG] 主知识库命中: vector_db_id=%s, avg_similarity=%.4f",
                        primary_vector_db.id,
                        primary_result["avg_similarity"],
                    )
                    return primary_result

            fallback_results = []
            if fallback_candidates:
                fallback_results = await asyncio.gather(*[
                    AsyncVectorService._query_single_vector_db_layer(
                        vector_db, layer, message,
                        n_results=LAYERED_RAG_MAX_CONTEXTS * 2 if use_unified_rerank else LAYERED_RAG_MAX_CONTEXTS,
                        prepared_query=prepared,
                        skip_rerank=use_unified_rerank,
                    )
                    for vector_db, layer in fallback_candidates
                ])

            # 全局 GraphRAG：与向量检索结果分开，作为上下文先验
            graph_context = ""
            try:
                from app.services.rag.graph_rag import global_graph_retrieval, format_triples_for_context, NEO4J_ENABLED
                if NEO4J_ENABLED:
                    graph_triples = await global_graph_retrieval(message)
                    if graph_triples:
                        graph_context = format_triples_for_context(graph_triples)
                        logger.info(f"🌐 [GraphRAG] 全局查询返回 {len(graph_triples)} 条三元组，注入上下文")
            except Exception as graph_err:
                logger.warning(f"全局 GraphRAG 查询失败（不影响向量检索）: {graph_err}")

            merged_inputs = []
            if primary_result:
                merged_inputs.append(primary_result)
            merged_inputs.extend(fallback_results)
            merged_result = AsyncVectorService._merge_layered_rag_results(merged_inputs)
            if graph_context:
                merged_result["graph_context"] = graph_context

            if use_unified_rerank and merged_result.get("sources"):
                try:
                    from app.services.rag.reranker import rerank
                    from app.services.rag.retrieval import RetrievalResult
                    candidates_for_rerank = [
                        RetrievalResult(
                            chunk_id=s.get("id", ""),
                            content=s.get("content", ""),
                            score=float(s.get("final_score", 0)),
                            vector_score=float(s.get("vector_score", 0)),
                            bm25_score=float(s.get("bm25_score", 0)),
                            similarity=float(s.get("similarity", 0)),
                            source=s.get("source", ""),
                            document_id=str(s.get("document_id", "")),
                            retrieval_method=s.get("retrieval_method", "hybrid"),
                            metadata={"vector_db_id": s.get("vector_db_id"), "vector_db_name": s.get("vector_db_name"), "retrieval_layer": s.get("retrieval_layer")},
                        )
                        for s in merged_result["sources"]
                    ]
                    reranked = await rerank(message, candidates_for_rerank, top_k=LAYERED_RAG_MAX_CONTEXTS)
                    reranked_sources = []
                    for r in reranked:
                        reranked_sources.append({
                            "id": r.chunk_id,
                            "content": r.content,
                            "source": r.source,
                            "distance": 1.0 - r.similarity,
                            "similarity": r.similarity,
                            "vector_score": r.vector_score,
                            "bm25_score": r.bm25_score,
                            "final_score": r.score,
                            "retrieval_method": r.retrieval_method,
                            "document_id": r.document_id,
                            "vector_db_id": r.metadata.get("vector_db_id"),
                            "vector_db_name": r.metadata.get("vector_db_name"),
                            "retrieval_layer": r.metadata.get("retrieval_layer"),
                        })
                    merged_result["sources"] = reranked_sources
                    merged_result["contexts"] = [s["content"] for s in reranked_sources]
                    merged_result["total_results"] = len(reranked_sources)
                    if reranked_sources:
                        merged_result["avg_similarity"] = sum(s["similarity"] for s in reranked_sources) / len(reranked_sources)
                    # Constraint-Boosted Rerank: 命中约束条件的文档加权
                    if prepared and prepared.constraints and prepared.constraints.has_constraints():
                        dept = prepared.constraints.department
                        year = prepared.constraints.year
                        boosted = 0
                        for s in reranked_sources:
                            boost = 1.0
                            s_content = s.get("content", "") + " " + s.get("source", "")
                            if dept and dept in s_content:
                                boost *= 1.3
                            if year and str(year) in s_content:
                                boost *= 1.15
                            if boost > 1.0:
                                s["similarity"] = min(1.0, s["similarity"] * boost)
                                s["final_score"] = s["final_score"] * boost
                                boosted += 1
                        if boosted:
                            reranked_sources.sort(key=lambda x: x["final_score"], reverse=True)
                            logger.info(f"🎯 [Constraint Boost] {boosted} 条文档命中约束加权 (dept={dept}, year={year})")

                    logger.info(f"✅ [RAG] 统一 Rerank 完成: {len(candidates_for_rerank)} → {len(reranked_sources)} 条")
                except Exception as e:
                    logger.warning(f"统一 Rerank 失败，使用粗排结果: {e}")

            logger.info(
                "✅ [RAG] 分层检索完成: queried=%s, selected=%s, layers=%s, avg_similarity=%.4f",
                merged_result["queried_vector_db_ids"],
                merged_result["vector_db_ids"],
                merged_result["retrieval_layers"],
                merged_result["avg_similarity"],
            )
            return merged_result
        except Exception as e:
            logger.error(f"❌ [RAG] 向量检索失败: {str(e)}", exc_info=True)
            return AsyncVectorService._empty_rag_result()
