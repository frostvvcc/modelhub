"""
用户服务集成测试（注册、登录、获取用户信息）
"""
import pytest
from app.services.user_service import AsyncUserService
from app.utils.JwtUtil import get_password_hash
from app.utils.error_handler import ConflictError, NotFoundError, UnauthorizedError, ValidationError
from app.models.user import User


@pytest.fixture
async def registered_user(db_session, test_school):
    """注册一个带学校的用户（密码已哈希）"""
    user = User(
        name="登录测试用户",
        email="login_test@example.com",
        password=get_password_hash("correct_password"),
        status="active",
        school_id=test_school.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ── 注册测试 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_basic(db_session):
    """测试基本注册"""
    result = await AsyncUserService.register(
        db_session,
        name="新用户",
        email="newuser@example.com",
        password="password123",
    )

    assert result["name"] == "新用户"
    assert result["email"] == "newuser@example.com"
    assert "token" in result
    assert result["token"] is not None


@pytest.mark.asyncio
async def test_register_with_school(db_session, test_school):
    """测试注册时关联学校"""
    result = await AsyncUserService.register(
        db_session,
        name="学校用户",
        email="school_user@example.com",
        password="password123",
        school_id=test_school.id,
        student_id="2024001",
    )

    assert result["school_id"] == test_school.id


@pytest.mark.asyncio
async def test_register_duplicate_email(db_session):
    """测试重复邮箱注册抛出 ConflictError"""
    await AsyncUserService.register(
        db_session,
        name="第一个用户",
        email="dup@example.com",
        password="password123",
    )

    with pytest.raises(ConflictError):
        await AsyncUserService.register(
            db_session,
            name="第二个用户",
            email="dup@example.com",
            password="another_password",
        )


@pytest.mark.asyncio
async def test_register_invalid_school(db_session):
    """测试关联不存在的学校抛出 ValidationError"""
    with pytest.raises(ValidationError):
        await AsyncUserService.register(
            db_session,
            name="无效学校用户",
            email="invalid_school@example.com",
            password="password123",
            school_id=99999,
        )


# ── 登录测试 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success(db_session, registered_user):
    """测试正确密码登录成功"""
    result = await AsyncUserService.login(
        db_session,
        email="login_test@example.com",
        password="correct_password",
    )

    assert result["email"] == "login_test@example.com"
    assert "token" in result
    assert result["token"] is not None
    assert "role" in result


@pytest.mark.asyncio
async def test_login_wrong_password(db_session, registered_user):
    """测试错误密码登录抛出 UnauthorizedError"""
    with pytest.raises(UnauthorizedError):
        await AsyncUserService.login(
            db_session,
            email="login_test@example.com",
            password="wrong_password",
        )


@pytest.mark.asyncio
async def test_login_nonexistent_user(db_session):
    """测试不存在的用户登录抛出 NotFoundError"""
    with pytest.raises(NotFoundError):
        await AsyncUserService.login(
            db_session,
            email="ghost@example.com",
            password="any_password",
        )


# ── 用户信息获取测试 ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_user_by_email(db_session, registered_user):
    """测试根据邮箱获取用户详细信息"""
    result = await AsyncUserService.get_user_by_email(db_session, "login_test@example.com")

    assert "user_info" in result
    assert "model_configs" in result
    assert "vector_dbs" in result
    assert "organizations" in result
    assert "roles" in result
    assert "permissions" in result
    assert result["user_info"]["email"] == "login_test@example.com"


@pytest.mark.asyncio
async def test_get_user_by_email_not_found(db_session):
    """测试不存在的用户抛出 NotFoundError"""
    with pytest.raises(NotFoundError):
        await AsyncUserService.get_user_by_email(db_session, "nobody@example.com")


# ── 其他用户操作 ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_enterprise_users(db_session):
    """测试获取企业用户列表（type=2 的企业用户）"""
    from app.models.user import User
    enterprise_user = User(name="企业用户", email="enterprise@example.com",
                           password="hashed", status="active", type=2)
    db_session.add(enterprise_user)
    await db_session.commit()
    await db_session.refresh(enterprise_user)

    users = await AsyncUserService.get_enterprise_users(db_session)
    assert isinstance(users, list)
    ids = [u["id"] for u in users]
    assert enterprise_user.id in ids


@pytest.mark.asyncio
async def test_update_avatar(db_session, test_user):
    """测试更新用户头像"""
    new_avatar = "https://example.com/avatar.png"
    result = await AsyncUserService.update_avatar(db_session, test_user.id, new_avatar)
    assert result == new_avatar


@pytest.mark.asyncio
async def test_update_avatar_not_found(db_session):
    """测试为不存在的用户更新头像抛出 NotFoundError"""
    with pytest.raises(NotFoundError):
        await AsyncUserService.update_avatar(db_session, 99999, "avatar.png")


@pytest.mark.asyncio
async def test_get_user_school(db_session, registered_user, test_school):
    """测试获取用户所属学校"""
    school = await AsyncUserService.get_user_school(db_session, registered_user.id)
    assert school is not None
    assert school["id"] == test_school.id


@pytest.mark.asyncio
async def test_get_user_school_no_school(db_session, test_user):
    """测试用户未关联学校时返回 None"""
    school = await AsyncUserService.get_user_school(db_session, test_user.id)
    assert school is None
