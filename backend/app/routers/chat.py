"""
对话路由
"""
from fastapi import APIRouter, Depends, status, Form, UploadFile, File
from typing import Optional, List
import json
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.utils.auth import get_current_user
from app.schemas.response import SuccessResponse
from app.models.user import User
from app.services.chat_service import AsyncChatService
from app.utils.logger_config import get_logger
from app.utils.error_handler import ValidationError

logger = get_logger(__name__)
router = APIRouter()


@router.post(
    "/",
    response_model=SuccessResponse[dict],
    summary="发送消息进行对话"
)
async def chat(
    conversation_id: Optional[int] = Form(None),
    model_config_id: Optional[int] = Form(None),
    message: str = Form(""),
    files: Optional[List[UploadFile]] = File(None),
    organization_id: Optional[int] = Form(None),
    vector_db_ids: Optional[str] = Form(None),
    quoted_content: Optional[str] = Form(None),
    quoted_role: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """发送消息进行对话"""
    file_count = len([file for file in (files or []) if file.filename])
    logger.info(
        "chat接口收到请求: user_id=%s, conversation_id=%s, model_config_id=%s, message长度=%s, 附件数=%s",
        current_user.id,
        conversation_id,
        model_config_id,
        len(message) if message else 0,
        file_count,
    )

    if not message and file_count == 0:
        logger.warning(f"[调试] message为空，抛出ValidationError")
        raise ValidationError("用户消息和附件不能同时为空")
    if not message and file_count > 0:
        message = "请总结并回答我上传的附件内容。"

    parsed_vector_db_ids: Optional[List[int]] = None
    if vector_db_ids:
        try:
            parsed_vector_db_ids = json.loads(vector_db_ids)
            if not isinstance(parsed_vector_db_ids, list):
                parsed_vector_db_ids = None
        except (json.JSONDecodeError, TypeError):
            parsed_vector_db_ids = None

    response = await AsyncChatService.chat(
        db,
        current_user.id,
        conversation_id,
        model_config_id,
        message,
        files=files,
        vector_db_ids=parsed_vector_db_ids,
        quoted_content=quoted_content,
        quoted_role=quoted_role,
    )
    return SuccessResponse(message="对话成功！", data=response)


@router.post(
    "/history",
    response_model=SuccessResponse[dict],
    summary="获取对话历史记录"
)
async def get_history(
    conversation_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取单个对话的历史记录"""
    # 异常由中间件统一处理
    history = await AsyncChatService.get_history(db, conversation_id, current_user.id)
    return SuccessResponse(message="历史记录获取成功！", data=history)


@router.get(
    "/histories",
    response_model=SuccessResponse[list],
    summary="获取对话列表"
)
async def get_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """获取用户的所有对话列表"""
    # 异常由中间件统一处理
    histories = await AsyncChatService.get_conversation(db, current_user.id)
    return SuccessResponse(message="历史记录获取成功！", data=histories)


@router.delete(
    "/delete",
    response_model=SuccessResponse[dict],
    summary="删除对话"
)
async def delete_conversation(
    conversation_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """删除对话"""
    # 异常由中间件统一处理
    res = await AsyncChatService.delete_conversation(db, conversation_id, current_user.id)
    return SuccessResponse(
        message="删除对话成功！",
        data={"delete": res, "msg": f"{conversation_id}已成功删除"}
    )


@router.post(
    "/set",
    response_model=SuccessResponse[dict],
    summary="设置对话历史消息数量"
)
async def set_chat_history(
    conversation_id: int = Form(...),
    chat_history: int = Form(..., ge=0, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """修改对话的 chat_history 参数"""
    # 异常由中间件统一处理
    res = await AsyncChatService.set_chat_history(db, conversation_id, chat_history, current_user.id)
    return SuccessResponse(message="修改chat_history成功！", data={"res": res})


@router.post(
    "/rechat",
    response_model=SuccessResponse[dict],
    summary="重新回答"
)
async def rechat(
    conversation_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """重新回答该问题"""
    # 异常由中间件统一处理
    response = await AsyncChatService.rechat(db, conversation_id, current_user.id)
    return SuccessResponse(message="对话成功", data=response)
