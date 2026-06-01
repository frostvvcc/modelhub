"""
Bot 业务逻辑服务
"""
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mappers.bot_mapper import AsyncBotMapper
from app.mappers.model_mapper import AsyncModelMapper
from app.mappers.organization_mapper import AsyncOrganizationMapper
from app.models.bot import Bot
from app.services.vector_service import AsyncVectorService
from app.services.simple_permission_service import ADMIN_ROLES, SimplePermissionService, UserRole
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


def check_forbidden_topics(user_message: str, forbidden_topics: List[str]) -> Optional[str]:
    for topic in (forbidden_topics or []):
        if topic and topic in user_message:
            logger.warning(f"消息命中禁止话题: [{topic}]")
            return topic
    return None


class AsyncBotService:
    @staticmethod
    async def _get_user_org_ids(db: AsyncSession, user) -> list[int]:
        """获取用户所在组织 ID，包含所有祖先组织（学校、学院等）。"""
        org_id_set: set[int] = set()
        if getattr(user, "school_id", None):
            org_id_set.add(user.school_id)
        try:
            user_orgs = await AsyncOrganizationMapper.get_user_organizations(db, user.id)
            for org in user_orgs:
                org_id_set.add(org.id)
                if org.school_id:
                    org_id_set.add(org.school_id)
                if org.path:
                    for ancestor_id in org.path.split('/'):
                        if ancestor_id:
                            org_id_set.add(int(ancestor_id))
        except Exception as exc:
            logger.warning("获取用户组织失败: user_id=%s (%s)", user.id, exc)
        return list(org_id_set)

    @staticmethod
    async def _normalize_payload(db: AsyncSession, user, data: dict) -> dict:
        """整理前端提交数据。"""
        payload = dict(data)

        # organization_id 逻辑：前端传什么就用什么，NULL 表示私有
        # 如果前端没传 organization_id 但传了旧字段，做兼容处理
        if "organization_id" not in payload and "org_id" in payload:
            payload["organization_id"] = payload.pop("org_id")
        payload.pop("org_id", None)
        payload.pop("visibility", None)
        payload.pop("school_id", None)

        payload["forbidden_topics"] = [
            topic.strip()
            for topic in (payload.get("forbidden_topics") or [])
            if isinstance(topic, str) and topic.strip()
        ]
        payload["vector_db_ids"] = [
            int(vector_db_id)
            for vector_db_id in (payload.get("vector_db_ids") or [])
            if vector_db_id
        ]
        return payload

    @staticmethod
    async def _assert_bot_config_access(
        db: AsyncSession, user, data: dict, *, skip_kb_check: bool = False
    ) -> None:
        """校验创建/更新 Bot 时，绑定的模型配置和知识库是否对当前用户可访问。"""
        user_role = await SimplePermissionService.get_user_role(db, user)
        org_ids = await AsyncBotService._get_user_org_ids(db, user)

        # 学生只能创建私有 Bot（organization_id=NULL）
        org_id = data.get("organization_id")
        if user_role == UserRole.STUDENT and org_id is not None:
            raise PermissionError("学生用户只能创建私有数字助理")

        # 老师只能将 Bot 发布到自己所属的组织
        if org_id and org_id not in org_ids and user_role not in ADMIN_ROLES:
            raise PermissionError("无权在该组织发布数字助理")

        model_config_id = data.get("model_config_id")
        if model_config_id:
            model_config = await AsyncModelMapper.get_model_config_by_id(db, int(model_config_id))
            if not model_config:
                raise ValueError("关联的模型配置不存在")
            if (
                user_role not in ADMIN_ROLES
                and model_config.user_id != user.id
                and not (model_config.organization_id and model_config.organization_id in org_ids)
            ):
                raise PermissionError("无权使用该模型配置")

        if not skip_kb_check:
            for vector_db_id in data.get("vector_db_ids") or []:
                has_access = await AsyncVectorService.check_vector_db_access(db, user.id, int(vector_db_id))
                if not has_access and user_role not in ADMIN_ROLES:
                    raise PermissionError(f"无权使用知识库 {vector_db_id}")

    @staticmethod
    async def create_bot(db: AsyncSession, user, data: dict) -> Bot:
        data = await AsyncBotService._normalize_payload(db, user, data)
        await AsyncBotService._assert_bot_config_access(db, user, data)
        return await AsyncBotMapper.create(db, user_id=user.id, **data)

    @staticmethod
    async def get_bot(db: AsyncSession, bot_id: int, user) -> Bot:
        bot = await AsyncBotMapper.get_by_id(db, bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} 不存在")

        user_role = await SimplePermissionService.get_user_role(db, user)
        if user_role in ADMIN_ROLES:
            return bot
        if bot.user_id == user.id:
            return bot

        # 根据 organization_id 判断
        if bot.organization_id:
            if await SimplePermissionService._user_belongs_to_org(db, user.id, user, bot.organization_id):
                return bot

        # 教学空间访问
        if await SimplePermissionService._user_has_teaching_space_access(db, user.id, "bot", bot_id):
            return bot

        raise PermissionError("无权访问该 Bot")

    @staticmethod
    async def _get_teaching_space_bot_ids(db: AsyncSession, user_org_ids: set[int]) -> set[int]:
        """获取用户通过教学空间可访问的 Bot ID 集合。"""
        from app.models.teaching_space import TeachingSpaceMajor, TeachingSpaceResource
        if not user_org_ids:
            return set()
        major_stmt = select(TeachingSpaceMajor.space_id).where(
            TeachingSpaceMajor.major_id.in_(user_org_ids)
        )
        result = await db.execute(major_stmt)
        space_ids = {row[0] for row in result.fetchall()}
        if not space_ids:
            return set()
        res_stmt = select(TeachingSpaceResource.resource_id).where(
            TeachingSpaceResource.space_id.in_(space_ids),
            TeachingSpaceResource.resource_type == "bot"
        )
        res_result = await db.execute(res_stmt)
        return {row[0] for row in res_result.fetchall()}

    @staticmethod
    async def list_bots(db: AsyncSession, user) -> List[Bot]:
        user_role = await SimplePermissionService.get_user_role(db, user)
        if user_role in ADMIN_ROLES:
            return await AsyncBotMapper.get_all(db)
        org_ids = await AsyncBotService._get_user_org_ids(db, user)
        ts_bot_ids = await AsyncBotService._get_teaching_space_bot_ids(db, set(org_ids))
        return await AsyncBotMapper.get_accessible(db, user.id, org_ids, ts_bot_ids)

    @staticmethod
    async def update_bot(db: AsyncSession, bot_id: int, user, data: dict) -> Bot:
        bot = await AsyncBotMapper.get_by_id(db, bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} 不存在")

        user_role = await SimplePermissionService.get_user_role(db, user)
        if bot.user_id != user.id and user_role not in ADMIN_ROLES:
            raise PermissionError("无权修改该 Bot")

        merged = bot.to_dict()
        merged.update(data)
        merged = await AsyncBotService._normalize_payload(db, user, merged)
        await AsyncBotService._assert_bot_config_access(db, user, merged)

        allowed_fields = {
            "name", "description", "avatar", "system_prompt", "greeting",
            "forbidden_topics", "model_config_id", "vector_db_ids",
            "organization_id",
        }
        update_data = {key: value for key, value in merged.items() if key in allowed_fields}
        return await AsyncBotMapper.update(db, bot_id, **update_data)

    @staticmethod
    async def delete_bot(db: AsyncSession, bot_id: int, user) -> bool:
        bot = await AsyncBotMapper.get_by_id(db, bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} 不存在")

        user_role = await SimplePermissionService.get_user_role(db, user)
        if bot.user_id != user.id and user_role not in ADMIN_ROLES:
            raise PermissionError("无权删除该 Bot")

        return await AsyncBotMapper.delete(db, bot_id)

    @staticmethod
    async def chat(
        db: AsyncSession,
        bot_id: int,
        user,
        message: str,
        conversation_id: Optional[str] = None,
    ) -> dict:
        bot = await AsyncBotService.get_bot(db, bot_id, user)

        hit = check_forbidden_topics(message, bot.forbidden_topics or [])
        if hit:
            return {
                'answer': f"抱歉，该话题（{hit}）不在本助理的服务范围内，请换个话题。",
                'conversation_id': conversation_id,
                'forbidden_topic_hit': hit,
            }

        from app.services.chat_service import AsyncChatService

        system_prompt = bot.system_prompt or ""
        if not bot.model_config_id:
            raise ValueError("数字助理未关联模型配���，无法对话")

        result = await AsyncChatService.bot_chat(
            db=db,
            user=user,
            message=message,
            conversation_id=conversation_id,
            system_prompt=system_prompt,
            vector_db_ids=bot.vector_db_ids or [],
            model_config_id=bot.model_config_id,
        )

        return {
            'answer': result['answer'],
            'conversation_id': result['conversation_id'],
            'forbidden_topic_hit': None,
            'model_name': result.get('model_name'),
            'rag_info': result.get('rag_info'),
            'sources': result.get('sources'),
            'grounded_ratio': result.get('grounded_ratio'),
            'grounded_level': result.get('grounded_level'),
        }
