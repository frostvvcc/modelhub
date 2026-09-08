"""
模型服务集成测试（ModelInfo + ModelConfig）
现行语义：ModelConfig 无 is_private/scope 字段，organization_id 为 NULL 即私有
"""
import uuid
import pytest
from app.services.model_service import AsyncModelService
from app.utils.error_handler import NotFoundError


# ── ModelInfo 测试 ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_all_model_info_empty(db_session):
    """无数据时返回空列表"""
    result = await AsyncModelService.get_all_info(db_session)
    assert result == []


@pytest.mark.asyncio
async def test_get_all_model_info(db_session, test_model_info):
    """有数据时返回列表"""
    result = await AsyncModelService.get_all_info(db_session)
    assert len(result) >= 1
    ids = [r["id"] for r in result]
    assert test_model_info.id in ids


@pytest.mark.asyncio
async def test_get_model_info_by_id(db_session, test_model_info):
    """根据 ID 获取模型信息"""
    result = await AsyncModelService.get_info(db_session, test_model_info.id)
    assert result["id"] == test_model_info.id
    assert result["model_name"] == test_model_info.model_name


@pytest.mark.asyncio
async def test_get_model_info_not_found(db_session):
    """获取不存在的模型信息抛出 NotFoundError"""
    with pytest.raises(NotFoundError):
        await AsyncModelService.get_info(db_session, 99999)


# ── ModelConfig 测试 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_model_config(db_session, test_user, test_model_info):
    """测试创建模型配置（未传 organization_id 即私有）"""
    share_id = str(uuid.uuid4())
    config = await AsyncModelService.create_model_config(
        db_session,
        user_id=test_user.id,
        share_id=share_id,
        base_model_id=test_model_info.id,
        name="测试配置",
        temperature=0.7,
        top_p=0.9,
        prompt="你是一个助手",
        describe="测试用配置",
    )

    assert config["name"] == "测试配置"
    assert config["base_model_id"] == test_model_info.id
    assert config["organization_id"] is None
    assert abs(config["temperature"] - 0.7) < 0.01


@pytest.mark.asyncio
async def test_get_model_config_by_id(db_session, test_user, test_model_info):
    """测试根据 ID 获取模型配置"""
    share_id = str(uuid.uuid4())
    created = await AsyncModelService.create_model_config(
        db_session,
        user_id=test_user.id,
        share_id=share_id,
        base_model_id=test_model_info.id,
        name="待获取配置",
        temperature=0.5,
        top_p=0.8,
        prompt=None,
    )

    fetched = await AsyncModelService.get_model_config_by_id(db_session, created["id"])
    assert fetched["id"] == created["id"]
    assert fetched["name"] == "待获取配置"


@pytest.mark.asyncio
async def test_get_model_config_not_found(db_session):
    """获取不存在的配置抛出 NotFoundError"""
    with pytest.raises(NotFoundError):
        await AsyncModelService.get_model_config_by_id(db_session, 99999)


@pytest.mark.asyncio
async def test_update_model_config(db_session, test_user, test_model_info):
    """测试更新模型配置"""
    share_id = str(uuid.uuid4())
    created = await AsyncModelService.create_model_config(
        db_session,
        user_id=test_user.id,
        share_id=share_id,
        base_model_id=test_model_info.id,
        name="待更新配置",
        temperature=0.7,
        top_p=0.9,
        prompt=None,
        describe="原始描述",
    )

    updated = await AsyncModelService.update_model_config(
        db_session,
        model_config_id=created["id"],
        name="更新后配置",
        describe="更新后描述",
        temperature=0.3,
    )

    assert updated["name"] == "更新后配置"
    assert updated["describe"] == "更新后描述"
    assert abs(updated["temperature"] - 0.3) < 0.01


@pytest.mark.asyncio
async def test_delete_model_config(db_session, test_user, test_model_info):
    """测试删除模型配置"""
    share_id = str(uuid.uuid4())
    created = await AsyncModelService.create_model_config(
        db_session,
        user_id=test_user.id,
        share_id=share_id,
        base_model_id=test_model_info.id,
        name="待删除配置",
        temperature=0.7,
        top_p=0.9,
        prompt=None,
    )

    deleted = await AsyncModelService.delete_model_config(db_session, created["id"])
    assert deleted["id"] == created["id"]

    with pytest.raises(NotFoundError):
        await AsyncModelService.get_model_config_by_id(db_session, created["id"])


@pytest.mark.asyncio
async def test_get_public_config_empty(db_session):
    """无公开配置时返回空列表"""
    result = await AsyncModelService.get_public_config(db_session)
    assert result == []


@pytest.mark.asyncio
async def test_get_user_config(db_session, test_user, test_model_info):
    """测试获取用户配置"""
    share_id = str(uuid.uuid4())
    await AsyncModelService.create_model_config(
        db_session,
        user_id=test_user.id,
        share_id=share_id,
        base_model_id=test_model_info.id,
        name="用户私有配置",
        temperature=0.7,
        top_p=0.9,
        prompt=None,
    )

    configs = await AsyncModelService.get_user_config(db_session, test_user)
    assert len(configs) >= 1
    names = [c["name"] for c in configs]
    assert "用户私有配置" in names
