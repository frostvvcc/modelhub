"""
供应商 API 集成测试
覆盖：GET /provider/providers, GET /provider/provider/{id}, POST /provider/provider
"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.__init__ import create_app
from app.database_async import get_async_db


async def grant_system_admin(db_session, user):
    user.role = "admin"
    await db_session.commit()
    await db_session.refresh(user)


@pytest.mark.asyncio
async def test_get_all_providers_api(db_session, test_user, test_provider, auth_headers, override_get_db):
    """GET /provider/providers — 返回供应商列表"""
    await grant_system_admin(db_session, test_user)
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/provider/providers", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["data"], list)
    assert len(data["data"]) >= 1


@pytest.mark.asyncio
async def test_get_provider_by_id_api(db_session, test_user, test_provider, auth_headers, override_get_db):
    """GET /provider/provider/{id} — 返回供应商详情"""
    await grant_system_admin(db_session, test_user)
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/provider/provider/{test_provider.id}",
            headers=auth_headers
        )

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["id"] == test_provider.id
    assert data["data"]["code"] == test_provider.code


@pytest.mark.asyncio
async def test_get_provider_not_found_api(db_session, test_user, auth_headers, override_get_db):
    """GET /provider/provider/{id} — 不存在时返回 404"""
    await grant_system_admin(db_session, test_user)
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/provider/provider/99999", headers=auth_headers)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_provider_api(db_session, test_user, auth_headers, override_get_db):
    """POST /provider/provider — 创建成功返回 201"""
    await grant_system_admin(db_session, test_user)
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/provider/provider",
            params={
                "name": "API创建供应商",
                "code": "api_provider",
                "provider_type": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "test-key",
            },
            headers=auth_headers
        )

    assert response.status_code == 201
    data = response.json()
    assert data["data"]["code"] == "api_provider"
