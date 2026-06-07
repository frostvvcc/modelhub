"""
Bot（数字助理）路由
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.utils.auth import get_current_user
from app.services.bot_service import AsyncBotService
from app.services.stream_chat_service import StreamChatService
from app.schemas.bot import BotCreate, BotUpdate, BotResponse, BotChatRequest, BotChatResponse
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


class BufferedUploadFile:
    """UploadFile-compatible wrapper backed by in-memory bytes."""

    def __init__(self, data: bytes, filename: str, content_type: str = "application/octet-stream"):
        from io import BytesIO
        self._buf = BytesIO(data)
        self.filename = filename
        self.content_type = content_type
        self.size = len(data)

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)

    async def seek(self, offset: int) -> None:
        self._buf.seek(offset)


router = APIRouter()


def _to_response(bot) -> dict:
    d = bot.to_dict()
    return d


@router.post("", response_model=BotResponse, status_code=status.HTTP_201_CREATED)
async def create_bot(
    payload: BotCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
):
    try:
        bot = await AsyncBotService.create_bot(db, current_user, payload.model_dump(exclude_none=True))
        return bot.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("", response_model=list)
async def list_bots(
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
):
    bots = await AsyncBotService.list_bots(db, current_user)
    return [b.to_dict() for b in bots]


@router.get("/own", response_model=list)
async def list_own_bots(
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
):
    """获取当前用户自己创建的数字助理"""
    from app.mappers.bot_mapper import AsyncBotMapper
    bots = await AsyncBotMapper.get_by_user(db, current_user.id)
    return [b.to_dict() for b in bots]


@router.get("/{bot_id}", response_model=BotResponse)
async def get_bot(
    bot_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
):
    try:
        bot = await AsyncBotService.get_bot(db, bot_id, current_user)
        return bot.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.put("/{bot_id}", response_model=BotResponse)
async def update_bot(
    bot_id: int,
    payload: BotUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
):
    try:
        bot = await AsyncBotService.update_bot(
            db, bot_id, current_user, payload.model_dump(exclude_none=True)
        )
        return bot.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(
    bot_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
):
    try:
        await AsyncBotService.delete_bot(db, bot_id, current_user)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/{bot_id}/chat", response_model=BotChatResponse)
async def bot_chat(
    bot_id: int,
    payload: BotChatRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
):
    try:
        result = await AsyncBotService.chat(
            db=db,
            bot_id=bot_id,
            user=current_user,
            message=payload.message,
            conversation_id=payload.conversation_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Bot 对话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"对话失败: {str(e)}")


@router.post("/{bot_id}/chat/stream")
async def bot_chat_stream(
    bot_id: int,
    message: str = Form(...),
    conversation_id: Optional[str] = Form(None),
    use_agent: bool = Form(True),
    files: Optional[List[UploadFile]] = File(None),
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
):
    """Bot 流式对话（SSE），支持文件上传"""
    try:
        from app.services.bot_service import check_forbidden_topics
        import json

        bot = await AsyncBotService.get_bot(db, bot_id, current_user)

        hit = check_forbidden_topics(message, bot.forbidden_topics or [])
        if hit:
            async def forbidden_stream():
                yield f"event: error\ndata: {json.dumps({'message': f'该话题（{hit}）不在本助理的服务范围内', 'forbidden_topic_hit': hit}, ensure_ascii=False)}\n\n"
            return StreamingResponse(forbidden_stream(), media_type="text/event-stream")

        if not bot.model_config_id:
            raise ValueError("数字助理未关联模型配置")

        buffered_files = None
        if files:
            buffered_files = []
            for f in files:
                data = await f.read()
                buffered_files.append(BufferedUploadFile(data, f.filename, f.content_type))

        return StreamingResponse(
            StreamChatService.bot_chat_stream(
                db=db,
                user=current_user,
                message=message,
                conversation_id=conversation_id,
                system_prompt=bot.system_prompt or "",
                vector_db_ids=bot.vector_db_ids or [],
                model_config_id=bot.model_config_id,
                use_agent=use_agent,
                bot_id=bot_id,
                files=buffered_files,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Bot 流式对话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
