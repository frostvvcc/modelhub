"""
权限服务单元测试
"""
import pytest
from app.services.permission_service import AsyncPermissionService
from app.models.permission import Role, Permission, RolePermission, UserRole


@pytest.mark.asyncio
async def test_create_role(db_session):
    """测试创建角色"""
    role = await AsyncPermissionService.create_role(
        db_session,
        name="测试角色",
        code="test_role",
        description="测试用角色",
        level="class",
        is_system=False
    )
    
    assert role is not None
    assert role["name"] == "测试角色"
    assert role["code"] == "test_role"
    assert role["level"] == "class"


@pytest.mark.asyncio
async def test_assign_permission_to_role(db_session, test_role, test_permission):
    """测试为角色分配权限"""
    result = await AsyncPermissionService.assign_permission_to_role(
        db_session,
        test_role.id,
        test_permission.id
    )
    
    assert result is not None
    
    # 验证权限已分配
    permissions = await AsyncPermissionService.get_role_permissions(db_session, test_role.id)
    assert len(permissions) > 0
    assert any(p["id"] == test_permission.id for p in permissions)


@pytest.mark.asyncio
async def test_check_permission(db_session, test_user, test_role, test_permission):
    """测试权限检查"""
    # 为用户分配角色
    await AsyncPermissionService.assign_role_to_user(
        db_session,
        test_user.id,
        test_role.id,
        None,
        None
    )
    
    # 为角色分配权限
    await AsyncPermissionService.assign_permission_to_role(
        db_session,
        test_role.id,
        test_permission.id
    )
    
    # 检查权限
    has_permission = await AsyncPermissionService.check_permission(
        db_session,
        test_user.id,
        test_permission.code,
        None
    )
    
    assert has_permission is True


@pytest.mark.asyncio
async def test_get_user_permissions(db_session, test_user, test_role, test_permission):
    """测试获取用户权限"""
    # 为用户分配角色
    await AsyncPermissionService.assign_role_to_user(
        db_session,
        test_user.id,
        test_role.id,
        None,
        None
    )
    
    # 为角色分配权限
    await AsyncPermissionService.assign_permission_to_role(
        db_session,
        test_role.id,
        test_permission.id
    )
    
    # 获取用户权限
    permissions = await AsyncPermissionService.get_user_permissions(db_session, test_user.id)
    
    assert len(permissions) > 0
    assert test_permission.code in permissions

