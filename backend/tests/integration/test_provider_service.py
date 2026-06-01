"""
供应商服务集成测试
"""
import pytest
from app.services.provider_service import AsyncProviderService
from app.utils.error_handler import NotFoundError, ValidationError


@pytest.mark.asyncio
async def test_create_provider(db_session):
    """测试创建供应商"""
    provider = await AsyncProviderService.create_provider(
        db_session,
        name="阿里云百炼",
        code="aliyun_dashscope",
        provider_type="aliyun",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-test-key",
        description="阿里云百炼平台",
        is_active=True,
        is_default=False,
        priority=1,
    )

    assert provider["name"] == "阿里云百炼"
    assert provider["code"] == "aliyun_dashscope"
    assert provider["provider_type"] == "aliyun"
    assert provider["is_active"] is True


@pytest.mark.asyncio
async def test_create_provider_invalid_type(db_session):
    """测试创建供应商时无效类型抛出 ValidationError"""
    with pytest.raises(ValidationError):
        await AsyncProviderService.create_provider(
            db_session,
            name="无效供应商",
            code="invalid_provider",
            provider_type="unknown_type",
            base_url="https://example.com",
        )


@pytest.mark.asyncio
async def test_get_provider(db_session, test_provider):
    """测试根据 ID 获取供应商"""
    provider = await AsyncProviderService.get_provider(db_session, test_provider.id)

    assert provider["id"] == test_provider.id
    assert provider["name"] == test_provider.name
    assert provider["code"] == test_provider.code


@pytest.mark.asyncio
async def test_get_provider_not_found(db_session):
    """测试获取不存在的供应商抛出 NotFoundError"""
    with pytest.raises(NotFoundError):
        await AsyncProviderService.get_provider(db_session, 99999)


@pytest.mark.asyncio
async def test_get_provider_by_code(db_session, test_provider):
    """测试根据 code 获取供应商"""
    provider = await AsyncProviderService.get_provider_by_code(db_session, test_provider.code)

    assert provider["id"] == test_provider.id
    assert provider["code"] == test_provider.code


@pytest.mark.asyncio
async def test_get_all_providers(db_session, test_provider):
    """测试获取所有供应商"""
    providers = await AsyncProviderService.get_all_providers(db_session)

    assert len(providers) >= 1
    ids = [p["id"] for p in providers]
    assert test_provider.id in ids


@pytest.mark.asyncio
async def test_get_all_providers_filtered_by_active(db_session, test_provider):
    """测试按 is_active 筛选供应商"""
    active_providers = await AsyncProviderService.get_all_providers(db_session, is_active=True)
    assert all(p["is_active"] is True for p in active_providers)


@pytest.mark.asyncio
async def test_get_default_provider(db_session, test_provider):
    """测试获取默认供应商"""
    provider = await AsyncProviderService.get_default_provider(db_session)

    assert provider is not None
    assert provider["is_default"] is True


@pytest.mark.asyncio
async def test_update_provider(db_session, test_provider):
    """测试更新供应商"""
    updated = await AsyncProviderService.update_provider(
        db_session,
        test_provider.id,
        name="更新后的供应商",
        description="更新后的描述",
    )

    assert updated["name"] == "更新后的供应商"
    assert updated["description"] == "更新后的描述"
    assert updated["id"] == test_provider.id


@pytest.mark.asyncio
async def test_delete_provider(db_session, test_provider):
    """测试删除供应商"""
    result = await AsyncProviderService.delete_provider(db_session, test_provider.id)
    assert result is True

    with pytest.raises(NotFoundError):
        await AsyncProviderService.get_provider(db_session, test_provider.id)
