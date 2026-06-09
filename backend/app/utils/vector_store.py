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
    def upsert(
        self,
        collection_name: str,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict],
    ) -> None:
        ...

    @abstractmethod
    def count(self, collection_name: str) -> int:
        ...

    @abstractmethod
    def get_or_create_collection(self, name: str, metadata: Optional[Dict] = None) -> Any:
        ...

    @abstractmethod
    def collection_metadata(self, collection_name: str) -> Dict:
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

    def upsert(self, collection_name, ids, embeddings, documents, metadatas):
        col = self.get_collection(collection_name)
        col.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    def count(self, collection_name) -> int:
        col = self.get_collection(collection_name)
        return col.count()

    def get_or_create_collection(self, name: str, metadata: Optional[Dict] = None) -> Any:
        return self.client.get_or_create_collection(name=name, metadata=metadata or {"hnsw:space": "cosine"})

    def collection_metadata(self, collection_name: str) -> Dict:
        col = self.get_collection(collection_name)
        return getattr(col, 'metadata', None) or {}

    def health_check(self) -> bool:
        try:
            self.client.heartbeat()
            return True
        except Exception:
            return False


class MilvusStore(VectorStore):
    """Milvus 实现（生产环境，使用 pymilvus 3.x MilvusClient API）"""

    SCALAR_FIELDS = ("document_id", "source", "folder_hierarchy", "parent_id")

    def __init__(self):
        from pymilvus import MilvusClient, DataType
        self._DataType = DataType

        host = os.getenv("MILVUS_HOST", "localhost")
        port = os.getenv("MILVUS_PORT", "19530")
        self._client = MilvusClient(uri=f"http://{host}:{port}")
        self._dim = int(os.getenv("MILVUS_EMBEDDING_DIM", "1024"))
        logger.info(f"Milvus 连接成功: {host}:{port}")

    def _ensure_collection(self, name: str):
        if not self._client.has_collection(name):
            schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("id", self._DataType.VARCHAR, is_primary=True, max_length=256)
            schema.add_field("embedding", self._DataType.FLOAT_VECTOR, dim=self._dim)
            schema.add_field("document", self._DataType.VARCHAR, max_length=65535)
            schema.add_field("document_id", self._DataType.VARCHAR, max_length=64, default_value="")
            schema.add_field("source", self._DataType.VARCHAR, max_length=512, default_value="")
            schema.add_field("folder_hierarchy", self._DataType.VARCHAR, max_length=256, default_value="")
            schema.add_field("parent_id", self._DataType.VARCHAR, max_length=64, default_value="")
            schema.add_field("metadata_json", self._DataType.VARCHAR, max_length=65535)

            index_params = self._client.prepare_index_params()
            index_params.add_index(field_name="embedding", index_type="HNSW", metric_type="COSINE",
                                   params={"M": 16, "efConstruction": 256})
            self._client.create_collection(collection_name=name, schema=schema, index_params=index_params)
        self._client.load_collection(name)

    def create_collection(self, name: str, metadata: Optional[Dict] = None) -> bool:
        try:
            self._ensure_collection(name)
            return True
        except Exception as e:
            logger.error(f"Milvus 创建集合失败 {name}: {e}")
            return False

    def get_collection(self, name: str) -> Any:
        self._ensure_collection(name)
        return name

    def delete_collection(self, name: str) -> bool:
        try:
            self._client.drop_collection(name)
            return True
        except Exception as e:
            logger.warning(f"Milvus 删除集合失败 {name}: {e}")
            return False

    def add(self, collection_name, ids, embeddings, documents, metadatas):
        import json
        self._ensure_collection(collection_name)
        data = [
            {"id": ids[i], "embedding": list(embeddings[i]), "document": documents[i],
             "document_id": str(metadatas[i].get("document_id", "")),
             "source": str(metadatas[i].get("source", "")),
             "folder_hierarchy": str(metadatas[i].get("folder_hierarchy", "")),
             "parent_id": str(metadatas[i].get("parent_id", "")),
             "metadata_json": json.dumps(metadatas[i], ensure_ascii=False)}
            for i in range(len(ids))
        ]
        self._client.insert(collection_name=collection_name, data=data)

    def _build_filter_expr(self, where: Optional[Dict]) -> Optional[str]:
        if not where:
            return None
        if "$and" in where:
            parts = [self._build_filter_expr(sub) for sub in where["$and"]]
            return " and ".join(f"({p})" for p in parts if p)
        conditions = []
        for k, v in where.items():
            if k.startswith("$"):
                continue
            if k in self.SCALAR_FIELDS:
                escaped = str(v).replace('"', '\\"')
                conditions.append(f'{k} == "{escaped}"')
            else:
                escaped = str(v).replace('"', '\\"')
                conditions.append(f'metadata_json like \'%"{k}": "{escaped}"%\'')
        return " and ".join(conditions) if conditions else None

    def query(self, collection_name, query_embedding, n_results=5, where=None):
        import json
        self._ensure_collection(collection_name)
        expr = self._build_filter_expr(where)

        results = self._client.search(
            collection_name=collection_name,
            data=[list(query_embedding)],
            limit=n_results,
            filter=expr,
            output_fields=["id", "document", "document_id", "source",
                           "folder_hierarchy", "parent_id", "metadata_json"],
            search_params={"metric_type": "COSINE", "params": {"ef": 128}},
        )

        ids, documents, metadatas, distances = [], [], [], []
        for hit in results[0]:
            entity = hit.get("entity", hit)
            ids.append(entity.get("id", hit.get("id", "")))
            documents.append(entity.get("document", ""))
            meta = json.loads(entity.get("metadata_json") or "{}")
            for sf in self.SCALAR_FIELDS:
                val = entity.get(sf)
                if val:
                    meta[sf] = val
            metadatas.append(meta)
            distances.append(hit.get("distance", 0.0))

        return {
            "ids": [ids],
            "documents": [documents],
            "metadatas": [metadatas],
            "distances": [distances],
        }

    def get_all(self, collection_name, include=None):
        import json
        self._ensure_collection(collection_name)
        results = self._client.query(
            collection_name=collection_name, filter="id != ''",
            output_fields=["id", "document", "metadata_json"], limit=100000,
        )
        ids = [r["id"] for r in results]
        documents = [r["document"] for r in results]
        metadatas = [json.loads(r.get("metadata_json") or "{}") for r in results]
        return {"ids": ids, "documents": documents, "metadatas": metadatas}

    def delete(self, collection_name, where=None, ids=None):
        self._ensure_collection(collection_name)
        if ids:
            self._client.delete(collection_name=collection_name, ids=ids)
        elif where:
            expr = self._build_filter_expr(where)
            if expr:
                self._client.delete(collection_name=collection_name, filter=expr)

    def upsert(self, collection_name, ids, embeddings, documents, metadatas):
        import json
        self._ensure_collection(collection_name)
        data = [
            {"id": ids[i], "embedding": list(embeddings[i]), "document": documents[i],
             "document_id": str(metadatas[i].get("document_id", "")),
             "source": str(metadatas[i].get("source", "")),
             "folder_hierarchy": str(metadatas[i].get("folder_hierarchy", "")),
             "parent_id": str(metadatas[i].get("parent_id", "")),
             "metadata_json": json.dumps(metadatas[i], ensure_ascii=False)}
            for i in range(len(ids))
        ]
        self._client.upsert(collection_name=collection_name, data=data)

    def count(self, collection_name) -> int:
        self._ensure_collection(collection_name)
        stats = self._client.get_collection_stats(collection_name)
        return stats.get("row_count", 0)

    def get_or_create_collection(self, name: str, metadata: Optional[Dict] = None) -> Any:
        self._ensure_collection(name)
        return name

    def collection_metadata(self, collection_name: str) -> Dict:
        return {"hnsw:space": "cosine"}

    def health_check(self) -> bool:
        try:
            return self._client.get_server_version() is not None
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
