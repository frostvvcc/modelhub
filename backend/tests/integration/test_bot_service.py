"""
Bot 服务集成测试（CRUD + 禁止话题检查）
不测试 chat()，因为需要真实 LLM 调用
"""
import pytest
from app.services.bot_service import AsyncBotService, check_forbidden_topics
from app.models.user import User


@pytest.fixture
async def teacher_user(db_session):
    """创建教师角色用户（用于测试 visibility 权限）"""
    user = User(
        name="测试教师",
        email="teacher@example.com",
        password="hashed",
        status="active",
        role="teacher",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ── 禁止话题纯函数测试（无需 DB）─────────────────────────────────────────────

def test_check_forbidden_topics_hit():
    """命中禁止话题时返回话题名"""
    hit = check_forbidden_topics("我想讨论赌博相关的问题", ["赌博", "色情"])
    assert hit == "赌博"


def test_check_forbidden_topics_no_hit():
    """未命中时返回 None"""
    hit = check_forbidden_topics("今天天气真好", ["赌博", "色情"])
    assert hit is None


def test_check_forbidden_topics_empty_list():
    """禁止话题列表为空时总是通过"""
    hit = check_forbidden_topics("任意消息", [])
    assert hit is None


def test_check_forbidden_topics_none_list():
    """禁止话题列表为 None 时总是通过"""
    hit = check_forbidden_topics("任意消息", None)
    assert hit is None


# ── Bot CRUD 集成测试 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_bot_private(db_session, test_user):
    """测试创建私有 Bot"""
    bot = await AsyncBotService.create_bot(
        db_session,
        test_user,
        {
            "name": "私有助手",
            "description": "测试 Bot",
            "system_prompt": "你是一个助手",
            "greeting": "你好！",
            "forbidden_topics": ["赌博"],
            "visibility": "private",
        },
    )

    assert bot.name == "私有助手"
    assert bot.visibility == "private"
    assert bot.user_id == test_user.id
    assert bot.forbidden_topics == ["赌博"]


@pytest.mark.asyncio
async def test_create_bot_public_by_teacher(db_session, teacher_user):
    """教师可以创建公开 Bot"""
    bot = await AsyncBotService.create_bot(
        db_session,
        teacher_user,
        {
            "name": "公开助手",
            "description": "公开 Bot",
            "visibility": "public",
        },
    )

    assert bot.name == "公开助手"
    assert bot.visibility == "public"


@pytest.mark.asyncio
async def test_create_bot_public_by_student_raises(db_session, test_user):
    """学生创建非私有 Bot 抛出 PermissionError"""
    # test_user 默认为 student（无角色记录 → SimplePermissionService 返回 STUDENT）
    with pytest.raises(PermissionError):
        await AsyncBotService.create_bot(
            db_session,
            test_user,
            {
                "name": "学生想公开的 Bot",
                "visibility": "public",
            },
        )


@pytest.mark.asyncio
async def test_get_bot(db_session, test_user):
    """测试获取 Bot"""
    bot = await AsyncBotService.create_bot(
        db_session,
        test_user,
        {"name": "待获取 Bot", "visibility": "private"},
    )

    fetched = await AsyncBotService.get_bot(db_session, bot.id, test_user)
    assert fetched.id == bot.id
    assert fetched.name == "待获取 Bot"


@pytest.mark.asyncio
async def test_get_bot_not_found(db_session, test_user):
    """获取不存在的 Bot 抛出 ValueError"""
    with pytest.raises(ValueError):
        await AsyncBotService.get_bot(db_session, 99999, test_user)


@pytest.mark.asyncio
async def test_get_bot_private_by_other_user(db_session, test_user, teacher_user):
    """其他用户无权访问私有 Bot"""
    bot = await AsyncBotService.create_bot(
        db_session,
        teacher_user,
        {"name": "教师私有 Bot", "visibility": "private"},
    )

    with pytest.raises(PermissionError):
        await AsyncBotService.get_bot(db_session, bot.id, test_user)


@pytest.mark.asyncio
async def test_list_bots(db_session, test_user):
    """测试列出 Bot"""
    await AsyncBotService.create_bot(
        db_session,
        test_user,
        {"name": "Bot A", "visibility": "private"},
    )
    await AsyncBotService.create_bot(
        db_session,
        test_user,
        {"name": "Bot B", "visibility": "private"},
    )

    bots = await AsyncBotService.list_bots(db_session, test_user)
    names = [b.name for b in bots]
    assert "Bot A" in names
    assert "Bot B" in names


@pytest.mark.asyncio
async def test_update_bot(db_session, test_user):
    """测试更新 Bot"""
    bot = await AsyncBotService.create_bot(
        db_session,
        test_user,
        {"name": "待更新 Bot", "visibility": "private"},
    )

    updated = await AsyncBotService.update_bot(
        db_session,
        bot.id,
        test_user,
        {"name": "更新后 Bot", "description": "新描述"},
    )

    assert updated.name == "更新后 Bot"
    assert updated.description == "新描述"


@pytest.mark.asyncio
async def test_update_bot_permission_denied(db_session, test_user, teacher_user):
    """其他用户无权更新 Bot"""
    bot = await AsyncBotService.create_bot(
        db_session,
        teacher_user,
        {"name": "教师 Bot", "visibility": "private"},
    )

    with pytest.raises(PermissionError):
        await AsyncBotService.update_bot(
            db_session,
            bot.id,
            test_user,
            {"name": "篡改名称"},
        )


@pytest.mark.asyncio
async def test_delete_bot(db_session, test_user):
    """测试删除 Bot"""
    bot = await AsyncBotService.create_bot(
        db_session,
        test_user,
        {"name": "待删除 Bot", "visibility": "private"},
    )

    result = await AsyncBotService.delete_bot(db_session, bot.id, test_user)
    assert result is True

    with pytest.raises(ValueError):
        await AsyncBotService.get_bot(db_session, bot.id, test_user)


@pytest.mark.asyncio
async def test_delete_bot_permission_denied(db_session, test_user, teacher_user):
    """其他用户无权删除 Bot"""
    bot = await AsyncBotService.create_bot(
        db_session,
        teacher_user,
        {"name": "受保护 Bot", "visibility": "private"},
    )

    with pytest.raises(PermissionError):
        await AsyncBotService.delete_bot(db_session, bot.id, test_user)
