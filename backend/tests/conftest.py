"""
测试配置和 fixtures
- 集成测试需要真实数据库（默认模式），运行时设置 INTEGRATION_TESTS=1
- 单元测试（tests/unit/）使用 mock，无需外部服务
"""
import os
import pytest

# ------------------------------------------------------------------
# 公共 fixtures（单元测试和集成测试共用）
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# 集成测试专用 fixtures（需要数据库）
# 仅当未设置 UNIT_TEST_ONLY=1 时加载
# ------------------------------------------------------------------

_IS_UNIT_ONLY = os.getenv("UNIT_TEST_ONLY", "0") == "1"

if not _IS_UNIT_ONLY:
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from app.extensions import Base
        from app.models import *  # noqa: F401, F403
        from app.database_async import get_async_db
        from app.utils.auth import create_access_token
        from app.models.user import User
        from app.models.organization import Organization
        from app.models.permission import Role, Permission
        from app.models.provider_config import ProviderConfig
        from app.models.model_info import ModelInfo
        from app.models.vector_db import VectorDb

        from sqlalchemy.pool import StaticPool

        @pytest.fixture(scope="function")
        async def db_session():
            """集成测试用数据库会话（StaticPool 共享连接，避免跨 event loop 问题）"""
            engine = create_async_engine(
                "sqlite+aiosqlite:///:memory:",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False,
            )
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with session_factory() as session:
                yield session
                await session.rollback()
            await engine.dispose()

        @pytest.fixture
        def override_get_db(db_session):
            async def _get_db():
                yield db_session
            return _get_db

        @pytest.fixture
        async def test_user(db_session):
            user = User(name="testuser", email="test@example.com",
                        password="hashed_password", status="active")
            db_session.add(user)
            await db_session.commit()
            await db_session.refresh(user)
            return user

        @pytest.fixture
        async def test_school(db_session):
            school = Organization(
                name="测试大学", code="TEST_UNIV", type="school",
                parent_id=None, school_id=None, level=1, path="/", status="active"
            )
            db_session.add(school)
            await db_session.commit()
            await db_session.refresh(school)
            return school

        @pytest.fixture
        async def test_role(db_session):
            role = Role(name="测试角色", code="test_role",
                        description="测试用角色", level="class", is_system=False)
            db_session.add(role)
            await db_session.commit()
            await db_session.refresh(role)
            return role

        @pytest.fixture
        async def test_permission(db_session):
            permission = Permission(
                name="测试权限", code="test:read", description="测试用权限",
                resource="test", action="read"
            )
            db_session.add(permission)
            await db_session.commit()
            await db_session.refresh(permission)
            return permission

        @pytest.fixture
        def test_token(test_user):
            return create_access_token({"id": test_user.id, "email": test_user.email})

        @pytest.fixture
        def auth_headers(test_token):
            return {"Authorization": f"Bearer {test_token}"}

        # ------------------------------------------------------------------
        # 供应商 / 模型 / 向量库 / Bot fixtures
        # ------------------------------------------------------------------

        @pytest.fixture
        async def test_provider(db_session):
            """创建测试供应商配置"""
            provider = ProviderConfig(
                name="测试供应商",
                code="test_openai",
                provider_type="openai",
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                is_active=True,
                is_default=True,
                priority=1,
            )
            db_session.add(provider)
            await db_session.commit()
            await db_session.refresh(provider)
            return provider

        @pytest.fixture
        async def test_model_info(db_session, test_provider):
            """创建测试 chatllm 模型"""
            model = ModelInfo(
                model_name="gpt-4-test",
                type="chatllm",
                provider_id=test_provider.id,
                describe="测试用模型",
                is_active=True,
            )
            db_session.add(model)
            await db_session.commit()
            await db_session.refresh(model)
            return model

        @pytest.fixture
        async def test_embedding_model(db_session, test_provider):
            """创建测试 embedding 模型"""
            model = ModelInfo(
                model_name="text-embedding-test",
                type="embedding",
                provider_id=test_provider.id,
                describe="测试用 Embedding 模型",
                is_active=True,
            )
            db_session.add(model)
            await db_session.commit()
            await db_session.refresh(model)
            return model

        @pytest.fixture
        async def test_vector_db(db_session, test_user, test_embedding_model):
            """创建测试向量数据库"""
            from app.models.vector_db import VectorDb
            vdb = VectorDb(
                user_id=test_user.id,
                embedding_id=test_embedding_model.id,
                name="test_knowledge_base",
                describe="测试知识库",
                scope="private",
            )
            db_session.add(vdb)
            await db_session.commit()
            await db_session.refresh(vdb)
            return vdb

    except Exception as _e:
        import warnings
        warnings.warn(f"集成测试 fixtures 加载失败（数据库不可用）: {_e}")
