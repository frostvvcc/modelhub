"""
Bot API 集成测试
覆盖：POST /bots, GET /bots, GET /bots/{id}, PUT /bots/{id}, DELETE /bots/{id}
"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.__init__ import create_app
from app.database_async import get_async_db


@pytest.mark.asyncio
async def test_create_bot_api(db_session, test_user, auth_headers, override_get_db):
    """POST /bots — 创建私有 Bot 成功"""
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/bots",
            json={"name": "API测试Bot", "description": "测试", "visibility": "private"},
            headers=auth_headers
        )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "API测试Bot"
    assert data["visibility"] == "private"
    assert data["user_id"] == test_user.id


@pytest.mark.asyncio
async def test_list_bots_api(db_session, test_user, auth_headers, override_get_db):
    """GET /bots — 返回当前用户可见 Bot 列表"""
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/bots",
            json={"name": "列表Bot", "visibility": "private"},
            headers=auth_headers
        )
        response = await client.get("/bots", headers=auth_headers)

    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) >= 1


@pytest.mark.asyncio
async def test_get_bot_api(db_session, test_user, auth_headers, override_get_db):
    """GET /bots/{id} — 获取 Bot 详情"""
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/bots",
            json={"name": "详情Bot", "visibility": "private"},
            headers=auth_headers
        )
        bot_id = create_resp.json()["id"]
        response = await client.get(f"/bots/{bot_id}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["id"] == bot_id


@pytest.mark.asyncio
async def test_get_bot_not_found_api(db_session, test_user, auth_headers, override_get_db):
    """GET /bots/{id} — 不存在时返回 404"""
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/bots/99999", headers=auth_headers)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_bot_api(db_session, test_user, auth_headers, override_get_db):
    """PUT /bots/{id} — 更新 Bot 名称"""
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/bots",
            json={"name": "原始名称", "visibility": "private"},
            headers=auth_headers
        )
        bot_id = create_resp.json()["id"]
        response = await client.put(
            f"/bots/{bot_id}",
            json={"name": "更新后名称"},
            headers=auth_headers
        )

    assert response.status_code == 200
    assert response.json()["name"] == "更新后名称"


@pytest.mark.asyncio
async def test_delete_bot_api(db_session, test_user, auth_headers, override_get_db):
    """DELETE /bots/{id} — 删除成功返回 204"""
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/bots",
            json={"name": "待删除Bot", "visibility": "private"},
            headers=auth_headers
        )
        bot_id = create_resp.json()["id"]
        response = await client.delete(f"/bots/{bot_id}", headers=auth_headers)

    assert response.status_code == 204
