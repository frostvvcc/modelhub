"""
Alembic 环境配置
"""
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import AsyncEngine
from alembic import context
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 绕过 app/__init__.py（避免触发路由/重型依赖 import 链）
import types as _types
_app_stub = _types.ModuleType('app')
_app_stub.__path__ = [str(project_root / 'app')]
_app_stub.__package__ = 'app'
sys.modules.setdefault('app', _app_stub)

from app.config import settings
from app.extensions import Base
# 直接导入各模型文件（不经过 app.models.__init__.py 的服务 import 链）
import importlib as _il
for _m in [
    'app.models.user', 'app.models.vector_db', 'app.models.model_info',
    'app.models.model_config', 'app.models.document', 'app.models.message',
    'app.models.conversation', 'app.models.organization', 'app.models.permission',
    'app.models.provider_config', 'app.models.bot', 'app.models.teaching_space',
]:
    _il.import_module(_m)

from urllib.parse import quote_plus

# this is the Alembic Config object
config = context.config

# 从应用配置获取数据库 URL
encoded_password = quote_plus(settings.db_password)
if settings.db_connection == "mysql":
    database_url = (
        f"mysql+pymysql://{settings.db_username}:{encoded_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_database}"
    )
else:
    database_url = settings.database_url

config.set_main_option("sqlalchemy.url", database_url)

# 如果配置了日志，使用它
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置目标元数据
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式运行迁移"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """运行迁移"""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式运行迁移"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

