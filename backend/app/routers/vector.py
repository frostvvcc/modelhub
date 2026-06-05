"""
向量数据库路由
"""
from fastapi import APIRouter, Depends, status, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from typing import List, Optional
import asyncio
import time
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database_async import get_async_db
from app.utils.auth import get_current_user
from app.utils.async_adapter import AsyncService
from app.schemas.vector import VectorDbCreate, VectorDbUpdate, VectorQueryRequest, VectorQueryWithHierarchyRequest
from app.schemas.response import SuccessResponse
from app.models.user import User
from app.models.document import Document
from app.services.vector_service import AsyncVectorService
from app.mappers.vector_mapper import AsyncVectorMapper
from app.utils.async_db import AsyncDB
from app.utils.logger_config import get_logger
from app.utils.error_handler import ValidationError, NotFoundError, ForbiddenError, InternalServerError
from app.services.simple_permission_service import ADMIN_ROLES, SimplePermissionService, UserRole

logger = get_logger(__name__)
router = APIRouter()


async def _require_vector_read(db: AsyncSession, user: User, vector_db_id: int) -> None:
    has_access = await AsyncVectorService.check_vector_db_access(db, user.id, vector_db_id)
    if not has_access:
        raise ForbiddenError("无权访问该知识库")


async def _require_vector_manage(db: AsyncSession, user: User, vector_db_id: int) -> None:
    vector_db = await AsyncVectorMapper.get_vector_db(db, vector_db_id)
    if not vector_db:
        raise NotFoundError("未找到该知识库")
    role = await SimplePermissionService.get_user_role(db, user)
    if role not in ADMIN_ROLES and vector_db.user_id != user.id:
        raise ForbiddenError("无权管理该知识库")


async def _require_document_manage(db: AsyncSession, user: User, document_id: int) -> Document:
    document = await AsyncDB.get_by_id(db, Document, document_id)
    if not document:
        raise NotFoundError("未找到该文件")
    can_delete = await SimplePermissionService.can_delete_document(db, user.id, document_id)
    if not can_delete:
        raise ForbiddenError("无权管理该文档")
    return document


async def _require_document_read(db: AsyncSession, user: User, document_id: int) -> Document:
    document = await AsyncDB.get_by_id(db, Document, document_id)
    if not document:
        raise NotFoundError("未找到该文件")
    await _require_vector_read(db, user, document.vector_db_id)
    return document


@router.post(
    "/create",
    response_model=SuccessResponse[dict],
    status_code=status.HTTP_201_CREATED,
    summary="创建向量数据库"
)
async def create_vector_db(
    name: str = Form(...),
    embedding_id: int = Form(...),
    describe: Optional[str] = Form(None),
    document_similarity: float = Form(0.7),
    organization_id: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """创建向量数据库"""
    if document_similarity < 0 or document_similarity > 1:
        raise ValidationError("document_similarity 必须在 0 到 1 之间")

    has_permission = await SimplePermissionService.check_vector_db_creation_permission(
        db, current_user.id, organization_id
    )
    if not has_permission:
        raise ForbiddenError("无权限创建知识库")

    vector_db = await AsyncVectorMapper.create_vector_db(
        db,
        current_user.id,
        name,
        embedding_id,
        describe,
        document_similarity=document_similarity,
        organization_id=organization_id,
    )

    success = await AsyncVectorService.create_chroma_collection(vector_db.id)
    if not success:
        logger.warning(f"无法为向量数据库 {vector_db.id} 创建ChromaDB集合")

    return SuccessResponse(message="创建成功", data=vector_db.to_dict())


@router.get(
    "/get/{vector_db_id}",
    response_model=SuccessResponse[dict],
    summary="获取向量数据库详情"
)
async def get_vector_db(
    vector_db_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取向���数据库详情"""
    vector_db_detail = await AsyncVectorService.get_vector_db(db, vector_db_id, current_user.id)
    return SuccessResponse(message="查询成功", data=vector_db_detail)


@router.post(
    "/update/{vector_db_id}",
    response_model=SuccessResponse[dict],
    summary="更新向量数据库"
)
async def update_vector_db(
    vector_db_id: int,
    request: VectorDbUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """更新向量数据库"""
    await _require_vector_manage(db, current_user, vector_db_id)

    vector_db = await AsyncVectorMapper.update_vector_db(
        db,
        vector_db_id,
        name=request.name,
        embedding_id=request.embedding_id,
        describe=request.describe,
        document_similarity=request.document_similarity,
        organization_id=request.organization_id,
    )

    if not vector_db:
        raise NotFoundError("未找到该向量数据库")

    return SuccessResponse(message="更新成功", data=vector_db.to_dict())


@router.delete(
    "/delete/{vector_db_id}",
    response_model=SuccessResponse[dict],
    summary="删除向量数据库"
)
async def delete_vector_db(
    vector_db_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """删除向量数据库"""
    await _require_vector_manage(db, current_user, vector_db_id)
    result = await AsyncVectorService.delete_vector_db(db, vector_db_id)
    if not result:
        raise NotFoundError("未找到该向量数据库")
    return SuccessResponse(message="删除成功")


@router.post(
    "/upload",
    response_model=SuccessResponse[dict],
    summary="上传���件到向量数据库（支持压缩包）"
)
async def upload_file(
    files: List[UploadFile] = File(...),
    vector_db_id: int = Form(...),
    describe: str = Form(""),
    parent_id: Optional[int] = Form(None),
    chunk_strategy: str = Form("markdown"),
    chunk_size: int = Form(800),
    chunk_overlap: int = Form(150),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """上传文件到向量数据库"""
    can_upload = await SimplePermissionService.can_upload_document(db, current_user.id, vector_db_id)
    if not can_upload:
        raise ForbiddenError("无权向该知识库上传文档")

    if not files or all(file.filename == '' for file in files):
        raise ValidationError("未选择文件")
    if chunk_strategy not in {"fixed", "sentence", "markdown"}:
        raise ValidationError("切块策略必须是 fixed、sentence 或 markdown")
    if chunk_size < 100 or chunk_size > 4000:
        raise ValidationError("chunk_size 必须在 100 到 4000 之间")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValidationError("chunk_overlap 必须大于等于 0 且小于 chunk_size")

    ALLOWED_EXTENSIONS = {
        '.pdf', '.docx', '.doc', '.txt', '.md',
        '.xlsx', '.xls', '.pptx', '.ppt',
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff',
        '.zip', '.tar', '.gz', '.rar',
    }
    ALLOWED_MIME_PREFIXES = (
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats',
        'application/vnd.ms-',
        'text/',
        'image/',
        'application/zip',
        'application/x-tar',
        'application/gzip',
        'application/x-rar',
    )
    import os as _os
    for _f in files:
        if _f.filename:
            ext = _os.path.splitext(_f.filename)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise ValidationError(f"不支持的文件类型: {ext}")
            if _f.content_type and not any(_f.content_type.startswith(p) for p in ALLOWED_MIME_PREFIXES):
                raise ValidationError(f"文件 {_f.filename} 的 MIME 类型不被允许: {_f.content_type}")

    from app.utils.archive_utils import is_archive_file

    document_ids = []
    failed_files = []
    for file in files:
        try:
            await file.seek(0)
            if is_archive_file(file.filename):
                logger.info(f"检测到压缩包: {file.filename}")
                archive_ids = await AsyncVectorService.upload_archive(
                    db,
                    vector_db_id=vector_db_id,
                    archive_file=file,
                    user_id=current_user.id,
                    describe=describe,
                    parent_id=parent_id,
                    chunk_strategy=chunk_strategy,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap
                )
                document_ids.extend(archive_ids)
            else:
                await file.seek(0)
                doc_id = await AsyncVectorService.upload_file(
                    db,
                    vector_db_id=vector_db_id,
                    file=file,
                    user_id=current_user.id,
                    describe=describe,
                    parent_id=parent_id,
                    chunk_strategy=chunk_strategy,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap
                )
                if doc_id:
                    document_ids.append(doc_id)
        except Exception as e:
            logger.error(f"文件上传失败: {file.filename}, 错误: {str(e)}", exc_info=True)
            failed_files.append({"filename": file.filename, "error": str(e)})

    if not document_ids and failed_files:
        raise InternalServerError(
            f"文件上传失败: {'; '.join(f['filename'] + ': ' + f['error'] for f in failed_files)}"
        )

    message = f"文件上传成功，共处理 {len(document_ids)} 个文档/文件夹"
    if failed_files:
        message += f"，{len(failed_files)} 个文件处理失败"

    return SuccessResponse(
        message=message,
        data={"document_ids": document_ids, "failed_files": failed_files}
    )


def _resolve_document_path(document) -> "Path":
    """解析文档物理路径，支持新旧两种存储位置"""
    from pathlib import Path
    if not document.save_path:
        raise NotFoundError("文件路径不存在")
    resolved = Path(document.save_path).resolve()
    if not resolved.is_file():
        raise NotFoundError("文件不存在或已被清理")
    if "knowledge_sources" not in str(resolved):
        raise ForbiddenError("非法文件路径")
    return resolved


@router.get(
    "/download_file/{document_id}",
    summary="下载文档",
    response_class=FileResponse
)
async def download_file(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """下载知识库中的原始文档。"""
    document = await _require_document_read(db, current_user, document_id)
    if document.is_folder:
        raise ValidationError("文件夹不能直接下载")
    resolved_path = _resolve_document_path(document)
    return FileResponse(
        path=str(resolved_path),
        filename=document.original_name or document.name,
        headers={"X-Content-Type-Options": "nosniff"}
    )


@router.get(
    "/preview/{document_id}",
    response_model=SuccessResponse[dict],
    summary="预览文档内容"
)
async def preview_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """预览文档的文本内容（提取前 5000 字符）。"""
    document = await _require_document_read(db, current_user, document_id)
    if document.is_folder:
        raise ValidationError("文件夹不能预览")
    resolved_path = _resolve_document_path(document)

    suffix = resolved_path.suffix.lower()
    max_chars = 5000

    if suffix in ('.txt', '.md'):
        for enc in ('utf-8', 'gbk', 'gb2312', 'latin-1'):
            try:
                text = resolved_path.read_text(encoding=enc)[:max_chars]
                break
            except (UnicodeDecodeError, ValueError):
                continue
        else:
            text = "[无法解码文件内容]"
    elif suffix in ('.docx', '.doc'):
        try:
            from app.services.rag.document_parser import extract_text
            full = extract_text(str(resolved_path)) or ""
            text = full[:max_chars]
        except Exception:
            text = "[文档解析失败]"
    elif suffix == '.pdf':
        try:
            from app.services.rag.document_parser import extract_text
            full = extract_text(str(resolved_path)) or ""
            text = full[:max_chars]
        except Exception:
            text = "[PDF 解析失败]"
    else:
        text = f"[不支持预览的文件类型: {suffix}]"

    return SuccessResponse(data={
        "id": document.id,
        "name": document.original_name or document.name,
        "type": suffix.lstrip('.'),
        "content": text,
        "truncated": len(text) >= max_chars,
    })


@router.delete(
    "/delete_file/{document_id}",
    response_model=SuccessResponse[dict],
    summary="删除文档"
)
async def delete_file(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """删除文档"""
    await _require_document_manage(db, current_user, document_id)
    result = await AsyncVectorService.delete_file(db, document_id)
    return SuccessResponse(message="文件删除成功")


@router.post(
    "/document/{document_id}/archive",
    response_model=SuccessResponse[dict],
    summary="归档文档"
)
async def archive_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """归档文档。"""
    await _require_document_manage(db, current_user, document_id)
    result = await AsyncVectorService.archive_document(db, document_id)
    return SuccessResponse(message="文档已归档", data=result)


@router.post(
    "/document/{document_id}/restore",
    response_model=SuccessResponse[dict],
    summary="恢复归档文档"
)
async def restore_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """恢复归档文档。"""
    await _require_document_manage(db, current_user, document_id)
    result = await AsyncVectorService.restore_document(db, document_id)
    return SuccessResponse(message="文档已恢复", data=result)


@router.delete(
    "/delete_folder_recursive/{document_id}",
    response_model=SuccessResponse[dict],
    summary="递归删除文件夹及其所有子项"
)
async def delete_folder_recursive(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """递归删除文件夹及其所有子项"""
    await _require_document_manage(db, current_user, document_id)
    stats = await AsyncVectorService.delete_folder_recursive(db, document_id)
    return SuccessResponse(
        message=f"删除成功: 文件夹{stats['folders']}个, 文件{stats['files']}个",
        data=stats
    )


@router.get(
    "/list",
    response_model=SuccessResponse[list],
    summary="获取用户可访问的向量数据库列表"
)
async def get_user_vector_db_list(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取用户可访问的向量数据库列表"""
    vector_dbs = await SimplePermissionService.get_accessible_vector_dbs(db, current_user.id)
    return SuccessResponse(message="查询成功", data=vector_dbs)


@router.get(
    "/list/own",
    response_model=SuccessResponse[list],
    summary="获��用户创建的向量数据库列表"
)
async def get_own_vector_db_list(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取用户创建的向量数据库列表"""
    vector_dbs = await AsyncVectorMapper.get_user_vector_dbs(db, current_user.id)
    vector_db_list = [{
        "id": vdb.id,
        "name": vdb.name,
        "describe": vdb.describe,
        "embedding_id": vdb.embedding_id,
        "document_similarity": float(vdb.document_similarity) if vdb.document_similarity else 0.7,
        "organization_id": vdb.organization_id,
        "created_at": vdb.create_at.isoformat() if vdb.create_at else None,
        "updated_at": vdb.update_at.isoformat() if vdb.update_at else None
    } for vdb in vector_dbs]
    return SuccessResponse(message="查询成功", data=vector_db_list)


@router.get(
    "/document/{document_id}",
    response_model=SuccessResponse[dict],
    summary="获取文档详情"
)
async def get_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取文档详情"""
    document = await AsyncDB.get_by_id(db, Document, document_id)
    if not document:
        raise NotFoundError("未找到该文件")
    await _require_vector_read(db, current_user, document.vector_db_id)
    return SuccessResponse(message="查询成功", data=document.to_dict())

@router.get(
    "/{vector_db_id}/documents/tree",
    response_model=SuccessResponse[list],
    summary="获取文档树形结构"
)
async def get_documents_tree(
    vector_db_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取向量数据库的文档树形结构"""
    await _require_vector_read(db, current_user, vector_db_id)
    tree = await AsyncVectorService.get_documents_tree(db, vector_db_id)
    return SuccessResponse(message="查询成功", data=tree)

@router.post(
    "/folder/create",
    response_model=SuccessResponse[dict],
    status_code=status.HTTP_201_CREATED,
    summary="创建文件夹"
)
async def create_folder(
    vector_db_id: int = Form(...),
    name: str = Form(...),
    parent_id: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """创建文件夹"""
    can_upload = await SimplePermissionService.can_upload_document(db, current_user.id, vector_db_id)
    if not can_upload:
        raise ForbiddenError("无权在该知识库创建文件夹")
    folder = await AsyncVectorService.create_folder(
        db, vector_db_id, name, parent_id, current_user.id
    )
    return SuccessResponse(message="文件夹创建成功", data=folder)

@router.post(
    "/document/{document_id}/rename",
    response_model=SuccessResponse[dict],
    summary="重命名文档或文件夹"
)
async def rename_document(
    document_id: int,
    new_name: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """重命名文档或文件夹"""
    await _require_document_manage(db, current_user, document_id)
    document = await AsyncVectorService.rename_document(db, document_id, new_name)
    return SuccessResponse(message="重命名成功", data=document)


@router.get(
    "/connect/{vector_id}",
    response_model=SuccessResponse[dict],
    summary="连接向量数据库"
)
async def connect_vector(
    vector_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """连接向量数据库"""
    await _require_vector_read(db, current_user, vector_id)
    await AsyncVectorService.ensure_collection_exists(vector_id)
    return SuccessResponse(message="连接成功")


@router.post(
    "/query/{vector_id}",
    response_model=SuccessResponse[list],
    summary="查询向量数据库"
)
async def query_vectors(
    vector_id: int,
    request: VectorQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """查询向量数据库"""
    await _require_vector_read(db, current_user, vector_id)
    result = await AsyncVectorService.query_vectors(
        vector_id,
        request.query_text,
        request.n_results
    )
    return SuccessResponse(message="查询成功", data=result)


@router.post(
    "/query_with_hierarchy/{vector_id}",
    response_model=SuccessResponse[list],
    summary="层级查询向量数据库"
)
async def query_vectors_with_hierarchy(
    vector_id: int,
    request: VectorQueryWithHierarchyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """支持层级过滤的向量数据库查询"""
    await _require_vector_read(db, current_user, vector_id)
    result = await AsyncVectorService.query_vectors_with_hierarchy(
        vector_id,
        request.query_text,
        request.n_results,
        request.folder_path,
        request.parent_id
    )
    return SuccessResponse(message="层级查询成功", data=result)


# ------------------------------------------------------------------
# 检索调试接口
# ------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel


class DebugQueryRequest(_BaseModel):
    query: str
    n_results: int = 10
    alpha: float = 0.7
    use_hybrid: bool = True
    use_rewrite: bool = False
    use_rerank: bool = False
    use_hyde: bool = False


class DebugResult(_BaseModel):
    rank: int
    chunk_id: str
    content: str
    source: str
    vector_score: float
    bm25_score: float
    rerank_score: float = 0.0
    final_score: float
    retrieval_method: str
    highlighted_terms: List[str]


class DebugQueryResponse(_BaseModel):
    query: str
    rewritten_queries: List[str] = []
    results: List[DebugResult]
    total_time_ms: float
    vector_search_time_ms: float
    bm25_search_time_ms: float
    alpha: float
    n_results: int
    pipeline: str


@router.post(
    "/{vector_id}/debug-query",
    response_model=DebugQueryResponse,
    summary="检索调试"
)
async def debug_query(
    vector_id: int,
    request: DebugQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    from app.services.rag.retrieval import VectorRetriever

    has_access = await AsyncVectorService.check_vector_db_access(db, current_user.id, vector_id)
    if not has_access:
        raise HTTPException(status_code=403, detail="无权访问该知识库")

    t0 = time.time()
    rewritten_queries: List[str] = []
    pipeline = "vector"

    # Step 1: Query 增强（可选）
    extra_queries: List[str] = []
    hyde_text = None
    if request.use_rewrite:
        from app.services.rag.query_rewriter import rewrite_query
        rewrites = await rewrite_query(request.query, n_rewrites=3)
        extra_queries = [q for q in rewrites if q != request.query]
        rewritten_queries = extra_queries
    if request.use_hyde:
        from app.services.rag.query_rewriter import hyde_rewrite
        hyde_text = await hyde_rewrite(request.query)

    # Step 2: 检索
    t_vec_start = time.time()
    all_queries = [request.query] + extra_queries
    use_enhanced = request.use_rewrite or request.use_hyde

    if use_enhanced or request.use_hybrid:
        t_bm25_start = time.time()
        tasks = [
            VectorRetriever.hybrid_query(
                vector_db_id=vector_id, query_text=q,
                n_results=request.n_results, alpha=request.alpha,
            )
            for q in all_queries
        ]
        if hyde_text:
            tasks.append(VectorRetriever.query(vector_id, hyde_text, request.n_results))

        multi_results = await asyncio.gather(*tasks)
        bm25_time = (time.time() - t_bm25_start) * 1000
        seen = set()
        results = []
        for batch in multi_results:
            for r in batch:
                if r.chunk_id not in seen:
                    results.append(r)
                    seen.add(r.chunk_id)
        results.sort(key=lambda r: r.score, reverse=True)
        pipeline = "enhanced" if use_enhanced else "hybrid"
    else:
        results = await VectorRetriever.query(
            vector_db_id=vector_id,
            query_text=request.query,
            n_results=request.n_results,
        )
        bm25_time = 0.0

    vector_time = (time.time() - t_vec_start) * 1000

    # Step 3: Rerank（可选）
    if request.use_rerank and len(results) > 1:
        from app.services.rag.reranker import rerank
        results = await rerank(request.query, results, top_k=request.n_results)
        pipeline = f"{pipeline}+rerank"

    total_time = (time.time() - t0) * 1000
    query_terms = VectorRetriever._tokenize(request.query)

    debug_results = []
    for rank, r in enumerate(results[:request.n_results], start=1):
        debug_results.append(DebugResult(
            rank=rank,
            chunk_id=r.chunk_id,
            content=r.content,
            source=r.source,
            vector_score=round(r.vector_score, 4),
            bm25_score=round(r.bm25_score, 4),
            rerank_score=round(r.rerank_score, 4),
            final_score=round(r.similarity, 4),
            retrieval_method=r.retrieval_method,
            highlighted_terms=[t for t in query_terms if t in r.content.lower()],
        ))

    return DebugQueryResponse(
        query=request.query,
        rewritten_queries=rewritten_queries,
        results=debug_results,
        total_time_ms=round(total_time, 2),
        vector_search_time_ms=round(vector_time, 2),
        bm25_search_time_ms=round(bm25_time, 2),
        alpha=request.alpha,
        n_results=request.n_results,
        pipeline=pipeline,
    )


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """查询 Celery 异步文档入库任务状态"""
    from app.celery_app import celery_app
    result = celery_app.AsyncResult(task_id)
    response = {"task_id": task_id, "state": result.state}
    if result.state == "PROGRESS":
        response["progress"] = result.info.get("progress", 0)
        response["step"] = result.info.get("step", "")
        response["current"] = result.info.get("current")
        response["total_chunks"] = result.info.get("total_chunks")
    elif result.state == "SUCCESS":
        response["result"] = result.result
    elif result.state == "FAILURE":
        response["error"] = str(result.result)
    return SuccessResponse(data=response)


@router.get("/rag/monitor")
async def get_rag_monitor_stats(
    current_user: User = Depends(get_current_user),
):
    """RAG 检索链路运行时监控（滑动窗口统计）"""
    if current_user.role not in ADMIN_ROLES:
        raise ForbiddenError("仅管理员可查看 RAG 监控")
    from app.services.rag.monitor import get_rag_monitor
    stats = get_rag_monitor().get_stats()
    return SuccessResponse(data=stats)
