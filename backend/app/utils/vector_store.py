"""
可插拔向量存储层（Strategy 模式）

支持 ChromaDB（开发环境）和 Milvus（生产环境）两种后端，
通过环境变量 VECTOR_STORE_BACKEND 切换，对上层业务代码透明。

使用方式：
    store = get_vector_store()
    store.create_collection("vector_db_1")
    store.add("vector_db_1", ids, embeddings, documents, metadatas)
    results = store.query("vector_db_1", query_embedding, n_results=5)
"""
import os
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

VECTOR_STORE_BACKEND = os.getenv("VECTOR_STORE_BACKEND", "chromadb").lower()


class VectorStore(ABC):
    """向量存储抽象接口"""

    @abstractmethod
    def create_collection(self, name: str, metadata: Optional[Dict] = None) -> bool:
        ...

    @abstractmethod
    def get_collection(self, name: str) -> Any:
        ...

    @abstractmethod
    def delete_collection(self, name: str) -> bool:
        ...

    @abstractmethod
    def add(
        self,
        collection_name: str,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict],
    ) -> None:
        ...

    @abstractmethod
    def query(
        self,
        collection_name: str,
        query_embedding: List[float],
        n_results: int = 5,
        where: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        ...

    @abstractmethod
    def get_all(
        self,
        collection_name: str,
        include: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        ...

    @abstractmethod
    def delete(self, collection_name: str, where: Optional[Dict] = None, ids: Optional[List[str]] = None) -> None:
        ...

    @abstractmethod
    def health_check(self) -> bool:
        ...


class ChromaDBStore(VectorStore):
    """ChromaDB 实现（开发环境，单机部署）"""

    def __init__(self):
        from app.utils.optimized_chromadb import get_chromadb_client
        self._get_client = get_chromadb_client

    @property
    def client(self):
        c = self._get_client()
        if not c:
            raise RuntimeError("ChromaDB 服务不可用")
        return c

    def create_collection(self, name: str, metadata: Optional[Dict] = None) -> bool:
        import chromadb.errors
        try:
            self.client.create_collection(name=name, metadata=metadata or {"hnsw:space": "cosine"})
            return True
        except chromadb.errors.UniqueConstraintError:
            return True
        except Exception as e:
            logger.error(f"ChromaDB 创建集合失败 {name}: {e}")
            return False

    def get_collection(self, name: str) -> Any:
        return self.client.get_collection(name=name)

    def delete_collection(self, name: str) -> bool:
        try:
            self.client.delete_collection(name)
            return True
        except Exception as e:
            logger.warning(f"ChromaDB 删除集合失败 {name}: {e}")
            return False

    def add(self, collection_name, ids, embeddings, documents, metadatas):
        col = self.get_collection(collection_name)
        col.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    def query(self, collection_name, query_embedding, n_results=5, where=None):
        col = self.get_collection(collection_name)
        kwargs = {"query_embeddings": [query_embedding], "n_results": n_results}
        if where:
            kwargs["where"] = where
        return col.query(**kwargs)

    def get_all(self, collection_name, include=None):
        col = self.get_collection(collection_name)
        return col.get(include=include or ["documents", "metadatas"])

    def delete(self, collection_name, where=None, ids=None):
        col = self.get_collection(collection_name)
        kwargs = {}
        if where:
            kwargs["where"] = where
        if ids:
            kwargs["ids"] = ids
        col.delete(**kwargs)

    def health_check(self) -> bool:
        try:
            self.client.heartbeat()
            return True
        except Exception:
            return False


class MilvusStore(VectorStore):
    """Milvus 实现（生产环境，支持十亿级向量 + HNSW 索引 + 分布式部署）"""

    def __init__(self):
        from pymilvus import connections, Collection, utility, FieldSchema, CollectionSchema, DataType
        self._connections = connections
        self._Collection = Collection
        self._utility = utility
        self._FieldSchema = FieldSchema
        self._CollectionSchema = CollectionSchema
        self._DataType = DataType

        host = os.getenv("MILVUS_HOST", "localhost")
        port = os.getenv("MILVUS_PORT", "19530")
        self._connections.connect("default", host=host, port=port)
        logger.info(f"Milvus 连接成功: {host}:{port}")

        self._dim = int(os.getenv("MILVUS_EMBEDDING_DIM", "1024"))

    def _ensure_collection(self, name: str):
        if not self._utility.has_collection(name):
            fields = [
                self._FieldSchema(name="id", dtype=self._DataType.VARCHAR, is_primary=True, max_length=256),
                self._FieldSchema(name="embedding", dtype=self._DataType.FLOAT_VECTOR, dim=self._dim),
                self._FieldSchema(name="document", dtype=self._DataType.VARCHAR, max_length=65535),
                self._FieldSchema(name="metadata_json", dtype=self._DataType.VARCHAR, max_length=65535),
            ]
            schema = self._CollectionSchema(fields, description=name)
            col = self._Collection(name, schema)
            col.create_index("embedding", {
                "index_type": "HNSW",
                "metric_type": "COSINE",
                "params": {"M": 16, "efConstruction": 256},
            })
            col.load()
            return col
        col = self._Collection(name)
        col.load()
        return col

    def create_collection(self, name: str, metadata: Optional[Dict] = None) -> bool:
        try:
            self._ensure_collection(name)
            return True
        except Exception as e:
            logger.error(f"Milvus 创建集合失败 {name}: {e}")
            return False

    def get_collection(self, name: str) -> Any:
        return self._ensure_collection(name)

    def delete_collection(self, name: str) -> bool:
        try:
            self._utility.drop_collection(name)
            return True
        except Exception as e:
            logger.warning(f"Milvus 删除集合失败 {name}: {e}")
            return False

    def add(self, collection_name, ids, embeddings, documents, metadatas):
        import json
        col = self._ensure_collection(collection_name)
        col.insert([
            ids,
            embeddings,
            documents,
            [json.dumps(m, ensure_ascii=False) for m in metadatas],
        ])
        col.flush()

    def query(self, collection_name, query_embedding, n_results=5, where=None):
        import json
        col = self._ensure_collection(collection_name)
        search_params = {"metric_type": "COSINE", "params": {"ef": 128}}
        expr = None
        if where:
            conditions = []
            for k, v in where.items():
                conditions.append(f'metadata_json like "%\\"{k}\\\": \\\"{v}\\\"%" ')
            expr = " and ".join(conditions) if conditions else None

        results = col.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=n_results,
            expr=expr,
            output_fields=["id", "document", "metadata_json"],
        )

        ids, documents, metadatas, distances = [], [], [], []
        for hit in results[0]:
            ids.append(hit.entity.get("id"))
            documents.append(hit.entity.get("document"))
            metadatas.append(json.loads(hit.entity.get("metadata_json") or "{}"))
            distances.append(hit.distance)

        return {
            "ids": [ids],
            "documents": [documents],
            "metadatas": [metadatas],
            "distances": [distances],
        }

    def get_all(self, collection_name, include=None):
        import json
        col = self._ensure_collection(collection_name)
        results = col.query(expr="id != ''", output_fields=["id", "document", "metadata_json"], limit=100000)
        ids = [r["id"] for r in results]
        documents = [r["document"] for r in results]
        metadatas = [json.loads(r.get("metadata_json") or "{}") for r in results]
        return {"ids": ids, "documents": documents, "metadatas": metadatas}

    def delete(self, collection_name, where=None, ids=None):
        col = self._ensure_collection(collection_name)
        if ids:
            expr = f'id in {ids}'
            col.delete(expr)
        elif where:
            for k, v in where.items():
                col.delete(f'metadata_json like "%\\"{k}\\\": {v}%"')
        col.flush()

    def health_check(self) -> bool:
        try:
            return self._utility.get_server_version() is not None
        except Exception:
            return False


_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """获取向量存储实例（单例，按 VECTOR_STORE_BACKEND 环境变量选择后端）"""
    global _vector_store
    if _vector_store is None:
        if VECTOR_STORE_BACKEND == "milvus":
            _vector_store = MilvusStore()
            logger.info("向量存储后端: Milvus")
        else:
            _vector_store = ChromaDBStore()
            logger.info("向量存储后端: ChromaDB")
    return _vector_store
