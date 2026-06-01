"""
组织API集成测试
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
async def test_create_organization_api(db_session, test_user, test_school, auth_headers, override_get_db):
    """测试创建组织API"""
    await grant_system_admin(db_session, test_user)
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/organization/create",
            headers=auth_headers,
            data={
                "name": "测试学院",
                "code": "TEST_COLLEGE",
                "org_type": "college",
                "parent_id": str(test_school.id),
                "school_id": str(test_school.id),
                "description": "测试用学院"
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["message"] == "创建成功"
        assert data["data"]["name"] == "测试学院"


@pytest.mark.asyncio
async def test_get_organization_tree_api(db_session, test_school, test_user, auth_headers, override_get_db):
    """测试获取组织树API"""
    await grant_system_admin(db_session, test_user)
    app = create_app()
    app.dependency_overrides[get_async_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/organization/{test_school.id}/tree",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "查询成功"
        assert data["data"]["id"] == test_school.id
