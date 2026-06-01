"""
FastAPI 数据库配置
使用异步数据库（推荐）

注意：此文件仅用于向后兼容，实际使用请从 database_async 导入
"""
from app.database_async import get_async_db, AsyncSessionLocal, async_engine
import logging

logger = logging.getLogger(__name__)

# 导入 app.models 中的所有模型，确保它们被注册
try:
    from app.models import User, VectorDb, ModelInfo, ModelConfig, Document, Message, Conversation
    logger.info("成功导入所有数据库模型")
except ImportError as e:
    logger.warning(f"无法导入 app.models: {e}，请确保 app 目录在 Python 路径中")

# 导出异步数据库相关对象（用于向后兼容）
__all__ = ['get_async_db', 'AsyncSessionLocal', 'async_engine']
