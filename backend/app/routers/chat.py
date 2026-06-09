"""
对话路由
"""
from fastapi import APIRouter, Depends, status, Form
from typing import Optional
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
    "/evaluate",
    response_model=SuccessResponse[dict],
    summary="RAG 质量评估"
)
async def evaluate_rag_quality(
    conversation_id: int = Form(...),
    message_index: int = Form(-1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    对指定对话的 RAG 回答进行质量评估（RAGAS 四指标）。
    message_index=-1 表示最后一条 assistant 消息。
    """
    from app.mappers.chat_mapper import AsyncChatMapper
    from app.services.rag.evaluation import evaluate_rag

    conversation = await AsyncChatMapper.get_conversation(db, conversation_id)
    if not conversation:
        raise ValidationError("对话不存在")

    messages = conversation["history"]["messages"]
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    user_msgs = [m for m in messages if m["role"] == "user"]

    if not assistant_msgs:
        raise ValidationError("对话中没有 assistant 回复")

    target = assistant_msgs[message_index] if abs(message_index) <= len(assistant_msgs) else assistant_msgs[-1]
    answer = target.get("content", "")
    metadata = target.get("metadata") or {}

    sources = metadata.get("sources", [])
    contexts = [s.get("content", "") for s in sources if s.get("content")]

    question = user_msgs[-1]["content"] if user_msgs else ""

    eval_result = await evaluate_rag(
        question=question,
        answer=answer,
        contexts=contexts,
    )

    return SuccessResponse(
        message="RAG 评估完成",
        data=eval_result.to_dict(),
    )


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
