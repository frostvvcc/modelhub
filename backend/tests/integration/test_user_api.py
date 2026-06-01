"""
用户 API 集成测试
覆盖：POST /user/register, POST /user/login, GET /user/info
"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.__init__ import create_app
from app.database_async import get_async_db


@pytest.mark.asyncio
async def test_register_api(db_session, override_get_db):
    """POST /user/register — 注册成功返回 token"""
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/user/register",
            json={"name": "API测试用户", "email": "apitest@example.com", "password": "Test1234!"}
        )

    assert response.status_code == 201
    data = response.json()
    assert data["message"] == "注册成功"
    assert "token" in data["data"]


@pytest.mark.asyncio
async def test_register_duplicate_api(db_session, override_get_db):
    """POST /user/register — 重复邮箱返回 409"""
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/user/register",
            json={"name": "用户A", "email": "dup@example.com", "password": "Test1234!"}
        )
        response = await client.post(
            "/user/register",
            json={"name": "用户B", "email": "dup@example.com", "password": "Test1234!"}
        )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login_api(db_session, override_get_db):
    """POST /user/login — 登录成功返回 token"""
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/user/register",
            json={"name": "登录测试", "email": "login@example.com", "password": "Test1234!"}
        )
        response = await client.post(
            "/user/login",
            json={"email": "login@example.com", "password": "Test1234!"}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "登录成功"
    assert "token" in data["data"]


@pytest.mark.asyncio
async def test_login_wrong_password_api(db_session, override_get_db):
    """POST /user/login — 密码错误返回 401"""
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/user/register",
            json={"name": "密码测试", "email": "pwd@example.com", "password": "Test1234!"}
        )
        response = await client.post(
            "/user/login",
            json={"email": "pwd@example.com", "password": "WrongPassword"}
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_user_info_api(db_session, test_user, auth_headers, override_get_db):
    """GET /user/info — 鉴权后返回用户信息"""
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/user/info", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["user_info"]["email"] == test_user.email


@pytest.mark.asyncio
async def test_get_user_info_unauthenticated_api(db_session, override_get_db):
    """GET /user/info — 无 token 返回 403"""
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/user/info")

    assert response.status_code == 403
