"""
单元测试隔离 conftest
在导入任何 app 模块之前，mock 掉需要外部服务（MySQL, Redis 等）的模块。
这使得单元测试无需真实数据库即可运行。
"""
import sys
import importlib
import types
from unittest.mock import MagicMock, AsyncMock

# ------------------------------------------------------------------
# 在 app 模块被 import 之前，mock 掉会触发数据库连接的模块
# ------------------------------------------------------------------

# Mock aiomysql / pymysql（避免 database_async.py 报 ImportError）
sys.modules.setdefault('aiomysql', MagicMock())
sys.modules.setdefault('pymysql', MagicMock())
sys.modules.setdefault('aiosqlite', MagicMock())

# Mock paddleocr（OCR 引擎，不在单元测试中需要）
_paddle_mock = MagicMock()
_paddle_mock.PaddleOCR = MagicMock
_paddle_mock.PPStructure = MagicMock
sys.modules.setdefault('paddleocr', _paddle_mock)
sys.modules.setdefault('paddle', MagicMock())

# Mock redis（缓存）
_redis_mock = MagicMock()
_redis_connection_mock = MagicMock()
_redis_connection_mock.ConnectionPool = MagicMock()
_redis_mock.connection = _redis_connection_mock
sys.modules.setdefault('redis', _redis_mock)
sys.modules.setdefault('redis.connection', _redis_connection_mock)
sys.modules.setdefault('redis.asyncio', MagicMock())

# Mock chromadb（向量数据库，retrieval 测试用 mock 覆盖）
_chromadb_mock = MagicMock()
_chromadb_errors_mock = MagicMock()
_chromadb_errors_mock.UniqueConstraintError = Exception
_chromadb_mock.errors = _chromadb_errors_mock
sys.modules.setdefault('chromadb', _chromadb_mock)
sys.modules.setdefault('chromadb.errors', _chromadb_errors_mock)

# Mock llama_index（大型 ML 框架）
try:
    from pydantic import Field as _PydanticField, PrivateAttr as _PydanticPrivateAttr
except Exception:
    _PydanticField = MagicMock
    _PydanticPrivateAttr = MagicMock


class _BaseEmbedding:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def get_query_embedding(self, query):
        return self._get_query_embedding(query)

    def get_text_embedding(self, text):
        return self._get_text_embedding(text)

    def get_text_embeddings(self, texts):
        return self._get_text_embeddings(texts)


_llama_core_mock = MagicMock()
_llama_core_llms_mock = MagicMock()
_llama_core_llms_mock.ChatMessage = MagicMock
_llama_core_embeddings_mock = types.ModuleType('llama_index.core.embeddings')
_llama_core_embeddings_mock.BaseEmbedding = _BaseEmbedding
_llama_bridge_mock = types.ModuleType('llama_index.core.bridge')
_llama_bridge_pydantic_mock = types.ModuleType('llama_index.core.bridge.pydantic')
_llama_bridge_pydantic_mock.Field = _PydanticField
_llama_bridge_pydantic_mock.PrivateAttr = _PydanticPrivateAttr
_llama_core_mock.llms = _llama_core_llms_mock
_llama_core_mock.embeddings = _llama_core_embeddings_mock
_llama_core_mock.bridge = _llama_bridge_mock
sys.modules.setdefault('llama_index', MagicMock())
sys.modules.setdefault('llama_index.core', _llama_core_mock)
sys.modules.setdefault('llama_index.core.llms', _llama_core_llms_mock)
sys.modules.setdefault('llama_index.core.embeddings', _llama_core_embeddings_mock)
sys.modules.setdefault('llama_index.core.bridge', _llama_bridge_mock)
sys.modules.setdefault('llama_index.core.bridge.pydantic', _llama_bridge_pydantic_mock)
sys.modules.setdefault('llama_index.vector_stores', MagicMock())
sys.modules.setdefault('llama_index.vector_stores.chroma', MagicMock())

# Mock sentence_transformers
sys.modules.setdefault('sentence_transformers', MagicMock())

# 拦截 app/__init__.py 中的数据库初始化（通过 mock database_async 模块）
_db_mock = MagicMock()
_db_mock.async_engine = MagicMock()
_db_mock.AsyncSessionLocal = MagicMock()
_db_mock.get_async_db = AsyncMock()
sys.modules.setdefault('app.database_async', _db_mock)

# unittest.mock.patch("app.services...") 需要父包 app 上有 services 属性。
try:
    import app as _app
    _services = importlib.import_module('app.services')
    setattr(_app, 'services', _services)
except Exception:
    pass
