"""
SimplePermissionService 单元测试
覆盖：角色判断、资源访问权限、操作权限、知识库专用权限
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.simple_permission_service import (
    SimplePermissionService,
    UserRole,
    check_resource_access,
    check_operation_permission,
)


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def make_user(uid=1, role="student"):
    u = MagicMock()
    u.id = uid
    u.role = role
    return u


def make_vector_db(uid=1, scope="private", org_id=None):
    vdb = MagicMock()
    vdb.user_id = uid
    vdb.scope = scope
    vdb.organization_id = org_id
    return vdb


def mock_empty_rbac_roles(db: AsyncMock) -> None:
    """让 get_user_role 的 RBAC 查询返回空，再走 User.role 兜底。"""
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)


# ------------------------------------------------------------------
# get_user_role
# ------------------------------------------------------------------

class TestGetUserRole:
    @pytest.mark.asyncio
    async def test_admin_from_role_field(self):
        db = AsyncMock()
        mock_empty_rbac_roles(db)
        user = make_user(role="admin")
        role = await SimplePermissionService.get_user_role(db, user)
        assert role == UserRole.ADMIN

    @pytest.mark.asyncio
    async def test_teacher_from_role_field(self):
        db = AsyncMock()
        mock_empty_rbac_roles(db)
        user = make_user(role="teacher")
        role = await SimplePermissionService.get_user_role(db, user)
        assert role == UserRole.TEACHER

    @pytest.mark.asyncio
    async def test_student_from_role_field(self):
        db = AsyncMock()
        mock_empty_rbac_roles(db)
        user = make_user(role="student")
        role = await SimplePermissionService.get_user_role(db, user)
        assert role == UserRole.STUDENT

    @pytest.mark.asyncio
    async def test_invalid_role_defaults_to_student(self):
        db = AsyncMock()
        # 无效角色值，应降级为 STUDENT（通过旧表查询路径，但 mock 返回空）
        user = make_user(role="invalid_role_xyz")
        from app.models.permission import UserRole as OldUserRole
        with patch("app.services.simple_permission_service.select") as mock_select:
            # 模拟数据库返回空结果（MagicMock 让 scalars().all() 同步调用正常工作）
            result_mock = MagicMock()
            result_mock.scalars.return_value.all.return_value = []
            db.execute = AsyncMock(return_value=result_mock)
            role = await SimplePermissionService.get_user_role(db, user)
        assert role == UserRole.STUDENT


# ------------------------------------------------------------------
# check_resource_access
# ------------------------------------------------------------------

class TestCheckResourceAccess:
    @pytest.mark.asyncio
    async def test_admin_always_has_access(self):
        db = AsyncMock()
        user = make_user(role="admin")
        resource = make_vector_db(uid=99, scope="private")
        result = await SimplePermissionService.check_resource_access(
            db, user, resource, UserRole.ADMIN
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_owner_has_access(self):
        db = AsyncMock()
        user = make_user(uid=5, role="teacher")
        resource = make_vector_db(uid=5, scope="private")
        result = await SimplePermissionService.check_resource_access(
            db, user, resource, UserRole.TEACHER
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_org_member_can_access_org_resource(self):
        db = AsyncMock()
        user = make_user(uid=10, role="student")
        resource = make_vector_db(uid=99, org_id=5)
        with patch.object(
            SimplePermissionService, "_user_belongs_to_org", AsyncMock(return_value=True)
        ):
            result = await SimplePermissionService.check_resource_access(
                db, user, resource, UserRole.STUDENT
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_private_resource_blocked_for_non_owner(self):
        db = AsyncMock()
        user = make_user(uid=10, role="student")
        resource = make_vector_db(uid=99, scope="private")
        with patch.object(
            SimplePermissionService, "_user_has_teaching_space_access", AsyncMock(return_value=False)
        ):
            result = await SimplePermissionService.check_resource_access(
                db, user, resource, UserRole.STUDENT
            )
        assert result is False


# ------------------------------------------------------------------
# check_operation_permission
# ------------------------------------------------------------------

class TestCheckOperationPermission:
    @pytest.mark.asyncio
    async def test_admin_can_do_anything(self):
        db = AsyncMock()
        user = make_user(role="admin")
        for op in ["create", "update", "delete", "read", "list"]:
            assert await SimplePermissionService.check_operation_permission(
                db, user, op, user_role=UserRole.ADMIN
            )

    @pytest.mark.asyncio
    async def test_student_cannot_create(self):
        db = AsyncMock()
        user = make_user(role="student")
        result = await SimplePermissionService.check_operation_permission(
            db, user, "create", user_role=UserRole.STUDENT
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_student_can_read(self):
        db = AsyncMock()
        user = make_user(role="student")
        result = await SimplePermissionService.check_operation_permission(
            db, user, "read", user_role=UserRole.STUDENT
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_teacher_can_update_own_resource(self):
        db = AsyncMock()
        user = make_user(uid=7, role="teacher")
        resource = make_vector_db(uid=7)
        result = await SimplePermissionService.check_operation_permission(
            db, user, "update", resource=resource, user_role=UserRole.TEACHER
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_teacher_cannot_update_others_resource(self):
        db = AsyncMock()
        user = make_user(uid=7, role="teacher")
        resource = make_vector_db(uid=99)
        result = await SimplePermissionService.check_operation_permission(
            db, user, "update", resource=resource, user_role=UserRole.TEACHER
        )
        assert result is False


# ------------------------------------------------------------------
# check_vector_db_creation_permission
# ------------------------------------------------------------------

class TestVectorDbCreationPermission:
    @pytest.mark.asyncio
    async def test_student_cannot_create(self):
        db = AsyncMock()
        with patch.object(
            SimplePermissionService, "_resolve_role_string", AsyncMock(return_value="student")
        ):
            result = await SimplePermissionService.check_vector_db_creation_permission(
                db, user_id=1
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_teacher_can_create(self):
        db = AsyncMock()
        with patch.object(
            SimplePermissionService, "_resolve_role_string", AsyncMock(return_value="teacher")
        ):
            result = await SimplePermissionService.check_vector_db_creation_permission(
                db, user_id=2
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_admin_can_create(self):
        db = AsyncMock()
        with patch.object(
            SimplePermissionService, "_resolve_role_string", AsyncMock(return_value="admin")
        ):
            result = await SimplePermissionService.check_vector_db_creation_permission(
                db, user_id=3, organization_id=5
            )
        assert result is True


# ------------------------------------------------------------------
# 便捷函数
# ------------------------------------------------------------------

class TestConvenienceFunctions:
    @pytest.mark.asyncio
    async def test_check_resource_access_shortcut(self):
        db = AsyncMock()
        user = make_user(role="admin")
        resource = make_vector_db(scope="private")
        result = await check_resource_access(db, user, resource, UserRole.ADMIN)
        assert result is True

    @pytest.mark.asyncio
    async def test_check_operation_permission_shortcut(self):
        db = AsyncMock()
        user = make_user(role="student")
        result = await check_operation_permission(db, user, "read", user_role=UserRole.STUDENT)
        assert result is True
