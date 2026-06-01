"""
组织服务集成测试
"""
import pytest
from app.services.organization_service import AsyncOrganizationService
from app.models.organization import Organization


@pytest.mark.asyncio
async def test_create_organization(db_session, test_school):
    """测试创建组织"""
    org = await AsyncOrganizationService.create_organization(
        db_session,
        name="测试学院",
        code="TEST_COLLEGE",
        org_type="college",
        parent_id=test_school.id,
        school_id=test_school.id,
        description="测试用学院"
    )

    assert org is not None
    assert org["name"] == "测试学院"
    assert org["code"] == "TEST_COLLEGE"
    assert org["type"] == "college"
    assert org["parent_id"] == test_school.id
    assert org["school_id"] == test_school.id
    assert org["level"] == 2  # 自动从 parent 推导


@pytest.mark.asyncio
async def test_get_organization_by_id(db_session, test_school):
    """测试根据ID获取组织"""
    org = await AsyncOrganizationService.get_organization(db_session, test_school.id)

    assert org is not None
    assert org["id"] == test_school.id
    assert org["name"] == "测试大学"


@pytest.mark.asyncio
async def test_get_organization_tree(db_session, test_school):
    """测试获取组织树"""
    # 创建子组织
    await AsyncOrganizationService.create_organization(
        db_session,
        name="测试学院",
        code="TEST_COLLEGE",
        org_type="college",
        parent_id=test_school.id,
        school_id=test_school.id,
        description="测试用学院"
    )

    tree = await AsyncOrganizationService.get_tree(db_session, test_school.id)

    assert tree is not None
    assert tree["id"] == test_school.id
    assert len(tree.get("children", [])) > 0


@pytest.mark.asyncio
async def test_update_organization(db_session, test_school):
    """测试更新组织"""
    updated = await AsyncOrganizationService.update_organization(
        db_session,
        test_school.id,
        name="更新后的大学",
        description="更新后的描述"
    )

    assert updated is not None
    assert updated["name"] == "更新后的大学"
    assert updated["description"] == "更新后的描述"
