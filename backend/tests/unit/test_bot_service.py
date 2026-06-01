"""
bot_service 单元测试
覆盖：禁止话题过滤、CRUD 权限、bot_chat 入口
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.bot_service import check_forbidden_topics, AsyncBotService
from app.services.simple_permission_service import UserRole


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def make_user(uid=1, role="student", school_id=None):
    u = MagicMock()
    u.id = uid
    u.role = role
    u.school_id = school_id
    return u


def make_bot(bid=1, user_id=1, visibility="private", forbidden_topics=None, vector_db_ids=None):
    b = MagicMock()
    b.id = bid
    b.user_id = user_id
    b.visibility = visibility
    b.forbidden_topics = forbidden_topics or []
    b.vector_db_ids = vector_db_ids or []
    b.org_id = None
    b.model_config_id = 10
    b.system_prompt = "你是一个助教"
    b.to_dict.return_value = {"id": bid}
    return b


# ------------------------------------------------------------------
# check_forbidden_topics
# ------------------------------------------------------------------

class TestCheckForbiddenTopics:
    def test_no_topics_always_passes(self):
        assert check_forbidden_topics("任何消息", []) is None

    def test_hit_returns_topic(self):
        result = check_forbidden_topics("我想讨论政治问题", ["政治", "暴力"])
        assert result == "政治"

    def test_no_hit_returns_none(self):
        assert check_forbidden_topics("今天天气真好", ["政治", "暴力"]) is None

    def test_empty_message(self):
        assert check_forbidden_topics("", ["政治"]) is None

    def test_none_topics_passes(self):
        assert check_forbidden_topics("随意消息", None) is None


# ------------------------------------------------------------------
# create_bot 权限
# ------------------------------------------------------------------

class TestCreateBot:
    @pytest.mark.asyncio
    async def test_student_can_create_private(self):
        db = AsyncMock()
        user = make_user(role="student")
        with patch("app.services.bot_service.SimplePermissionService.get_user_role",
                   return_value=UserRole.STUDENT), \
             patch("app.services.bot_service.AsyncBotService._get_user_org_ids",
                   AsyncMock(return_value=[])), \
             patch("app.services.bot_service.AsyncBotMapper.create",
                   return_value=make_bot()) as mock_create:
            bot = await AsyncBotService.create_bot(db, user, {"name": "test", "visibility": "private"})
            assert bot is not None
            mock_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_student_cannot_create_public(self):
        db = AsyncMock()
        user = make_user(role="student")
        with patch("app.services.bot_service.SimplePermissionService.get_user_role",
                   return_value=UserRole.STUDENT), \
             patch("app.services.bot_service.AsyncBotService._get_user_org_ids",
                   AsyncMock(return_value=[])):
            with pytest.raises(PermissionError):
                await AsyncBotService.create_bot(db, user, {"name": "test", "visibility": "public"})

    @pytest.mark.asyncio
    async def test_teacher_can_create_public(self):
        db = AsyncMock()
        user = make_user(role="teacher")
        with patch("app.services.bot_service.SimplePermissionService.get_user_role",
                   return_value=UserRole.TEACHER), \
             patch("app.services.bot_service.AsyncBotService._get_user_org_ids",
                   AsyncMock(return_value=[])), \
             patch("app.services.bot_service.AsyncBotMapper.create",
                   return_value=make_bot(visibility="public")) as mock_create:
            bot = await AsyncBotService.create_bot(db, user, {"name": "test", "visibility": "public"})
            assert bot is not None


# ------------------------------------------------------------------
# delete_bot 权限
# ------------------------------------------------------------------

class TestDeleteBot:
    @pytest.mark.asyncio
    async def test_owner_can_delete(self):
        db = AsyncMock()
        user = make_user(uid=1)
        bot = make_bot(user_id=1)
        with patch("app.services.bot_service.AsyncBotMapper.get_by_id", return_value=bot), \
             patch("app.services.bot_service.SimplePermissionService.get_user_role",
                   return_value=UserRole.STUDENT), \
             patch("app.services.bot_service.AsyncBotMapper.delete", return_value=True):
            result = await AsyncBotService.delete_bot(db, 1, user)
            assert result is True

    @pytest.mark.asyncio
    async def test_non_owner_cannot_delete(self):
        db = AsyncMock()
        user = make_user(uid=2)
        bot = make_bot(user_id=1)
        with patch("app.services.bot_service.AsyncBotMapper.get_by_id", return_value=bot), \
             patch("app.services.bot_service.SimplePermissionService.get_user_role",
                   return_value=UserRole.STUDENT):
            with pytest.raises(PermissionError):
                await AsyncBotService.delete_bot(db, 1, user)

    @pytest.mark.asyncio
    async def test_admin_can_delete_any(self):
        db = AsyncMock()
        user = make_user(uid=99, role="admin")
        bot = make_bot(user_id=1)
        with patch("app.services.bot_service.AsyncBotMapper.get_by_id", return_value=bot), \
             patch("app.services.bot_service.SimplePermissionService.get_user_role",
                   return_value=UserRole.ADMIN), \
             patch("app.services.bot_service.AsyncBotMapper.delete", return_value=True):
            result = await AsyncBotService.delete_bot(db, 1, user)
            assert result is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_raises(self):
        db = AsyncMock()
        user = make_user()
        with patch("app.services.bot_service.AsyncBotMapper.get_by_id", return_value=None):
            with pytest.raises(ValueError):
                await AsyncBotService.delete_bot(db, 999, user)


# ------------------------------------------------------------------
# chat — 禁止话题拦截
# ------------------------------------------------------------------

class TestBotChat:
    @pytest.mark.asyncio
    async def test_forbidden_topic_blocks_llm(self):
        db = AsyncMock()
        user = make_user()
        bot = make_bot(forbidden_topics=["政治"])
        with patch("app.services.bot_service.AsyncBotService.get_bot", return_value=bot):
            result = await AsyncBotService.chat(db, 1, user, "讨论一下政治问题", None)
            assert result["forbidden_topic_hit"] == "政治"
            assert "政治" in result["answer"]

    @pytest.mark.asyncio
    async def test_normal_message_calls_chat_service(self):
        import sys
        db = AsyncMock()
        user = make_user()
        bot = make_bot(forbidden_topics=["政治"])

        # 通过 patch.dict 注入 mock chat_service，避免深度 import 链问题
        _mock_chat_svc = MagicMock()
        _mock_chat_svc.AsyncChatService.bot_chat = AsyncMock(return_value={
            "answer": "答案内容",
            "conversation_id": "conv-1",
            "rag_info": None,
            "sources": None,
            "grounded_ratio": None,
            "grounded_level": None,
        })

        with patch.dict(sys.modules, {'app.services.chat_service': _mock_chat_svc}), \
             patch("app.services.bot_service.AsyncBotService.get_bot", return_value=bot), \
             patch("app.services.bot_service.AsyncBotService._assert_bot_config_access", AsyncMock()):
            result = await AsyncBotService.chat(db, 1, user, "请介绍一下Python", None)

        assert result["forbidden_topic_hit"] is None
        assert result["answer"] == "答案内容"
