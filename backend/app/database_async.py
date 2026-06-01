"""
FastAPI 异步数据库配置
使用 SQLAlchemy 2.0 异步支持
需要安装: pip install aiomysql 或 asyncpg
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import settings
import logging

logger = logging.getLogger(__name__)


def get_async_database_url() -> str:
    """
    生成异步数据库连接 URL
    
    MySQL: mysql+aiomysql://
    PostgreSQL: postgresql+asyncpg://
    """
    from urllib.parse import quote_plus
    encoded_password = quote_plus(settings.db_password)
    if settings.db_connection == "mysql":
        # 使用 aiomysql 驱动
        return (
            f"mysql+aiomysql://{settings.db_username}:{encoded_password}"
            f"@{settings.db_host}:{settings.db_port}/{settings.db_database}"
        )
    elif settings.db_connection == "postgresql":
        # 使用 asyncpg 驱动
        return (
            f"postgresql+asyncpg://{settings.db_username}:{encoded_password}"
            f"@{settings.db_host}:{settings.db_port}/{settings.db_database}"
        )
    else:
        raise ValueError(f"不支持的数据库类型: {settings.db_connection}")


# 创建异步数据库引擎
async_engine = create_async_engine(
    get_async_database_url(),
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=True,
    pool_timeout=settings.db_pool_timeout,
    echo=False,
    future=True
)

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# 创建基础模型类
AsyncBase = declarative_base()

# 导入 app.models 中的所有模型，确保它们被注册
try:
    from app.models import User, VectorDb, ModelInfo, ModelConfig, Document, Message, Conversation
    logger.info("成功导入所有数据库模型（异步版本）")
except ImportError as e:
    logger.warning(f"无法导入 app.models: {e}，请确保 app 目录在 Python 路径中")

# 使用 SQLAlchemy 的元数据
try:
    from app.extensions import Base
    # 使用模型的元数据
    metadata = Base.metadata
except ImportError:
    metadata = AsyncBase.metadata


async def get_async_db():
    """
    异步数据库会话依赖注入
    使用 yield 确保会话在使用后正确关闭
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# 辅助函数：将同步查询转换为异步
async def async_query(session: AsyncSession, query_func, *args, **kwargs):
    """
    执行异步查询
    
    Args:
        session: 异步会话
        query_func: 查询函数（如 lambda: db.query(User).filter_by(...).first()）
        *args: 位置参数
        **kwargs: 关键字参数
    
    Returns:
        查询结果
    """
    # 如果 query_func 是 lambda，需要执行它
    if callable(query_func):
        query = query_func()
        result = await session.execute(query)
        return result.scalars().first() if hasattr(result, 'scalars') else result
    return None

