"""
异步对话 Mapper
"""
import json
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, update, func
from app.models.conversation import Conversation
from app.models.message import Message
from app.utils.optimized_redis import OptimizedConversationStore
from app.utils.async_db import AsyncDB
from app.utils.error_handler import InternalServerError, NotFoundError
import logging

logger = logging.getLogger(__name__)


class AsyncChatMapper:
    """异步对话数据访问层"""
    _redis_store = OptimizedConversationStore()
    redis_client = _redis_store.redis_client
    prefix = "chat:"
    
    @staticmethod
    def _format_key(conversation_id: int) -> str:
        """格式化对话键"""
        return f"{AsyncChatMapper.prefix}{conversation_id}"
    
    @staticmethod
    async def create_conversation(
        session: AsyncSession,
        user_id: int,
        name: str,
        model_config_id: int,
        chat_history: int = 10,
        organization_id: Optional[int] = None,
        school_id: Optional[int] = None
    ) -> int:
        """创建对话（支持组织关联）"""
        try:
            conversation = Conversation(
                user_id=user_id,
                name=name,
                model_config_id=model_config_id,
                chat_history=chat_history,
                organization_id=organization_id,
                school_id=school_id
            )
            conversation = await AsyncDB.create(session, conversation)
            await AsyncDB.commit(session)
            return conversation.id
        except Exception as e:
            await AsyncDB.rollback(session)
            logger.error(f"创建对话失败: {e}", exc_info=True)
            raise InternalServerError(f"创建对话失败: {str(e)}")
    
    @staticmethod
    async def save_message(
        session: AsyncSession,
        conversation_id: int,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """保存消息"""
        try:
            key = AsyncChatMapper._format_key(conversation_id)
            message = {"role": role, "content": content}

            # 保存到数据库
            message_db = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
            )
            message_db = await AsyncDB.create(session, message_db)

            # 同步更新对话的 update_at，确保历史列表按最新消息排序
            stmt = update(Conversation).where(
                Conversation.id == conversation_id
            ).values(update_at=func.now())
            await session.execute(stmt)

            await AsyncDB.commit(session)

            # 尝试保存到 Redis（可选）
            try:
                AsyncChatMapper.redis_client.rpush(key, str(message))
            except Exception as redis_error:
                logger.warning(f"Redis 保存失败（消息已保存到数据库）: {redis_error}")

            return {
                "role": message_db.role,
                "content": message_db.content
            }
        except Exception as e:
            await AsyncDB.rollback(session)
            logger.error(f"消息添加失败: {e}", exc_info=True)
            raise InternalServerError(f"保存消息失败: {str(e)}")
    
    @staticmethod
    async def get_conversation_id(session: AsyncSession, user_id: int) -> list:
        """根据用户 ID 获取对话 ID 列表"""
        try:
            conversations = await AsyncDB.filter_by(session, Conversation, user_id=user_id)
            return [{"conversation_id": conv.id} for conv in conversations]
        except Exception as e:
            logger.error(f"获取用户对话失败: {e}", exc_info=True)
            raise InternalServerError(f"获取用户对话失败: {str(e)}")
    
    @staticmethod
    async def get_conversation_info(session: AsyncSession, conversation_id: int) -> dict:
        """获取对话信息"""
        try:
            conversation = await AsyncDB.get_by_id(session, Conversation, conversation_id)
            if not conversation:
                raise NotFoundError("对话不存在")
            return {
                "id": conversation.id,
                "user_id": conversation.user_id,
                "name": conversation.name,
                "model_config_id": conversation.model_config_id,
                "chat_history": conversation.chat_history,
                "type": 0,
                "organization_id": conversation.organization_id,
                "school_id": conversation.school_id,
                "create_at": conversation.create_at.isoformat() if conversation.create_at else None,
                "update_at": conversation.update_at.isoformat() if conversation.update_at else None
            }
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"获取对话信息失败: {e}", exc_info=True)
            raise InternalServerError(f"获取对话信息失败: {str(e)}")
    
    @staticmethod
    def _message_to_dict(m: Message) -> dict:
        """将 Message ORM 对象转为字典，含 metadata 展开。"""
        d: Dict[str, Any] = {
            "role": m.role,
            "content": m.content,
            "create_at": m.create_at.isoformat() if m.create_at else None,
        }
        if m.metadata_json:
            try:
                d.update(json.loads(m.metadata_json))
            except (json.JSONDecodeError, TypeError):
                pass
        return d

    @staticmethod
    async def get_all_history(session: AsyncSession, conversation_id: int) -> dict:
        """获取所有历史消息"""
        try:
            stmt = select(Message).where(
                Message.conversation_id == conversation_id
            ).order_by(desc(Message.create_at))

            result = await session.execute(stmt)
            messages_list = result.scalars().all()

            messages = [AsyncChatMapper._message_to_dict(m) for m in messages_list]

            return {
                "messages": messages,
                "count": len(messages)
            }
        except Exception as e:
            logger.error(f"查询对话历史记录失败: {e}", exc_info=True)
            raise InternalServerError(f"查询对话历史记录失败: {str(e)}")
    
    @staticmethod
    async def get_history(
        session: AsyncSession,
        conversation_id: int,
        length: int
    ) -> dict:
        """获取指定长度的历史消息"""
        try:
            stmt = select(Message).where(
                Message.conversation_id == conversation_id
            ).order_by(desc(Message.create_at)).limit(length)

            result = await session.execute(stmt)
            messages_list = result.scalars().all()

            messages = [AsyncChatMapper._message_to_dict(m) for m in messages_list]

            return {
                "messages": messages,
                "count": len(messages)
            }
        except Exception as e:
            logger.error(f"查询对话历史记录失败: {e}", exc_info=True)
            raise InternalServerError(f"查询对话历史记录失败: {str(e)}")
    
    @staticmethod
    async def get_conversation(
        session: AsyncSession,
        conversation_id: int,
        length: Optional[int] = None
    ) -> dict:
        """获取对话（包含信息和历史）"""
        try:
            conversation_info = await AsyncChatMapper.get_conversation_info(session, conversation_id)
            if not length:
                length = conversation_info["chat_history"]
            history = await AsyncChatMapper.get_history(session, conversation_id, length)
            return {
                "conversation_info": conversation_info,
                "history": history
            }
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"获取用户对话失败: {e}", exc_info=True)
            raise InternalServerError(f"获取用户对话失败: {str(e)}")
    
    @staticmethod
    async def delete_conversation(session: AsyncSession, conversation_id: int) -> int:
        """删除对话"""
        try:
            # 删除数据库中的消息
            messages = await AsyncDB.filter_by(session, Message, conversation_id=conversation_id)
            for message in messages:
                await AsyncDB.delete(session, message)
            
            # 删除对话
            conversation = await AsyncDB.get_by_id(session, Conversation, conversation_id)
            if conversation:
                await AsyncDB.delete(session, conversation)
            
            await AsyncDB.commit(session)

            # 尝试删除 Redis 中的对话（可选）
            try:
                key = AsyncChatMapper._format_key(conversation_id)
                AsyncChatMapper.redis_client.delete(key)
            except Exception as redis_error:
                # Redis 连接失败不影响功能，数据库中的记录已删除
                logger.warning(f"Redis 删除失败（数据库记录已删除）: {redis_error}")

            return True
        except Exception as e:
            await AsyncDB.rollback(session)
            logger.error(f"对话删除失败: {e}", exc_info=True)
            raise InternalServerError(f"对话删除失败: {str(e)}")
    
    @staticmethod
    async def set_chat_history(
        session: AsyncSession,
        conversation_id: int,
        chat_history: int
    ) -> dict:
        """设置对话历史消息数量"""
        try:
            conversation = await AsyncDB.get_by_id(session, Conversation, conversation_id)
            if not conversation:
                raise NotFoundError("对话不存在")
            
            previous_chat_history = conversation.chat_history
            conversation.chat_history = chat_history
            
            conversation = await AsyncDB.update(session, conversation)
            await AsyncDB.commit(session)
            
            return {
                "conversation_id": conversation_id,
                "previous_chat_history": previous_chat_history,
                "new_chat_history": conversation.chat_history
            }
        except Exception as e:
            await AsyncDB.rollback(session)
            logger.error(f"参数修改失败: {e}", exc_info=True)
            raise InternalServerError(f"参数修改失败: {str(e)}")
