"""
项目根 conftest.py（最先执行）
在所有测试的 conftest 之前 mock 外部服务依赖，
使单元测试无需安装 MySQL / Redis / PaddleOCR 等外部依赖即可运行。

运行集成测试（需要真实服务）：INTEGRATION_TESTS=1 pytest tests/integration/
运行单元测试（默认，无需外部服务）：pytest tests/unit/
"""
import sys
import os
import types
from unittest.mock import MagicMock, AsyncMock

# 集成测试模式（INTEGRATION_TESTS=1）：跳过所有 heavy mocks，允许真实模块导入
if os.getenv("INTEGRATION_TESTS", "0") != "1":

    # ------------------------------------------------------------------
    # 注入 stub 包：绕过 app/__init__.py 等的模块级路由/服务导入
    # 必须在任何 app.* 导入之前执行
    # ------------------------------------------------------------------
    def _make_stub_pkg(name: str, path: str) -> types.ModuleType:
        """创建一个只有 __path__ 的空包，让子模块可以正常导入，但跳过 __init__.py"""
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        mod.__file__ = os.path.join(path, '__init__.py')
        mod.__spec__ = None
        return mod

    _base = os.path.dirname(__file__)
    sys.modules.setdefault('app', _make_stub_pkg('app', os.path.join(_base, 'app')))
    sys.modules.setdefault('app.services', _make_stub_pkg('app.services', os.path.join(_base, 'app', 'services')))
    sys.modules.setdefault('app.services.rag', _make_stub_pkg('app.services.rag', os.path.join(_base, 'app', 'services', 'rag')))

    # ------------------------------------------------------------------
    # 数据库驱动 mock（必须在 SQLAlchemy 初始化之前）
    # ------------------------------------------------------------------
    sys.modules.setdefault('aiomysql', MagicMock())
    sys.modules.setdefault('pymysql', MagicMock())
    sys.modules.setdefault('aiosqlite', MagicMock())

    # mock create_async_engine 避免 module-level DB 连接
    import unittest.mock as _mock
    import sqlalchemy.ext.asyncio as _sa_async
    _sa_async.create_async_engine = _mock.MagicMock(return_value=MagicMock())

    # ------------------------------------------------------------------
    # 其他重型依赖 mock
    # ------------------------------------------------------------------
    _paddle_mock = MagicMock()
    _paddle_mock.PaddleOCR = MagicMock
    _paddle_mock.PPStructure = MagicMock
    sys.modules.setdefault('paddleocr', _paddle_mock)
    sys.modules.setdefault('paddle', MagicMock())
    sys.modules.setdefault('paddle.fluid', MagicMock())

    # Redis - 必须显式 mock 所有子模块，否则 `from redis.connection import X` 会失败
    _redis_mock = MagicMock()
    _redis_connection_mock = MagicMock()
    _redis_connection_mock.ConnectionPool = MagicMock
    _redis_mock.connection = _redis_connection_mock
    sys.modules['redis'] = _redis_mock
    sys.modules['redis.asyncio'] = MagicMock()
    sys.modules['redis.connection'] = _redis_connection_mock
    sys.modules['redis.client'] = MagicMock()
    sys.modules['redis.exceptions'] = MagicMock()

    # ChromaDB — 显式 mock 所有已知子模块
    _chroma_config_mock = MagicMock()
    _chroma_config_mock.Settings = MagicMock
    _chroma = MagicMock()
    _chroma_err = MagicMock()
    _chroma_err.UniqueConstraintError = Exception
    _chroma.errors = _chroma_err
    _chroma.config = _chroma_config_mock
    sys.modules.setdefault('chromadb', _chroma)
    sys.modules.setdefault('chromadb.errors', _chroma_err)
    sys.modules.setdefault('chromadb.config', _chroma_config_mock)
    sys.modules.setdefault('chromadb.api', MagicMock())
    sys.modules.setdefault('chromadb.api.types', MagicMock())
    sys.modules.setdefault('chromadb.utils', MagicMock())

    # LlamaIndex — 显式 mock 所有已知子模块（包括 llms/embeddings/bridge，
    # 避免 from...llms 或 from...bridge.pydantic 导入失败）
    from pydantic import Field as _PydanticField, PrivateAttr as _PydanticPrivateAttr

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

    _llama_core_llms_mock = MagicMock()
    _llama_core_llms_mock.ChatMessage = MagicMock
    _llama_core_embeddings_mock = types.ModuleType('llama_index.core.embeddings')
    _llama_core_embeddings_mock.BaseEmbedding = _BaseEmbedding
    _llama_bridge_mock = types.ModuleType('llama_index.core.bridge')
    _llama_bridge_pydantic_mock = types.ModuleType('llama_index.core.bridge.pydantic')
    _llama_bridge_pydantic_mock.Field = _PydanticField
    _llama_bridge_pydantic_mock.PrivateAttr = _PydanticPrivateAttr
    _llama_core_mock = MagicMock()
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

    # sentence-transformers
    sys.modules.setdefault('sentence_transformers', MagicMock())

    # doc2text, pdfplumber（可选依赖）
    sys.modules.setdefault('doc2text', MagicMock())
    sys.modules.setdefault('pdfplumber', MagicMock())

    # JWT / 认证
    sys.modules.setdefault('jose', MagicMock())
    sys.modules.setdefault('jose.JWTError', MagicMock())
    _jose_mock = sys.modules['jose']
    _jose_mock.JWTError = Exception
    _jose_mock.jwt = MagicMock()

    sys.modules.setdefault('passlib', MagicMock())
    sys.modules.setdefault('passlib.context', MagicMock())
    _passlib_ctx = MagicMock()
    _passlib_ctx.CryptContext = MagicMock
    sys.modules['passlib.context'] = _passlib_ctx

    # langchain
    sys.modules.setdefault('langchain', MagicMock())

    # PIL / Pillow
    sys.modules.setdefault('PIL', MagicMock())
    sys.modules.setdefault('PIL.Image', MagicMock())
    sys.modules.setdefault('PIL.ImageEnhance', MagicMock())

    # numpy
    sys.modules.setdefault('numpy', MagicMock())

    # tencentcloud
    sys.modules.setdefault('tencentcloud', MagicMock())

    # chardet（编码检测，如未安装则 mock）
    _chardet_mock = MagicMock()
    _chardet_mock.detect = lambda data: {'encoding': 'utf-8', 'confidence': 0.99}
    sys.modules.setdefault('chardet', _chardet_mock)
