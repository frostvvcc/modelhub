"""
Elasticsearch 全文检索模块

替代内存 BM25，支持分布式部署、IK 中文分词、增量索引。
通过 ES_ENABLED 环境变量控制开关，未启用时 retrieval.py 自动降级为内存 BM25。
"""
import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

import time as _time

ES_ENABLED = os.getenv("ES_ENABLED", "true").lower() in ("true", "1", "yes")
ES_URL = os.getenv("ES_URL", "http://localhost:9200")

_es_client = None
_es_last_failure: float = 0.0
_ES_COOLDOWN = 60


async def get_es_client():
    global _es_client, _es_last_failure
    if not ES_ENABLED:
        return None
    if _es_client is not None:
        return _es_client
    if _time.monotonic() - _es_last_failure < _ES_COOLDOWN:
        return None
    try:
        from elasticsearch import AsyncElasticsearch
        client = AsyncElasticsearch(ES_URL, request_timeout=5)
        info = await client.info()
        _es_client = client
        logger.info(f"Elasticsearch 连接成功: {ES_URL}, version={info['version']['number']}")
    except ImportError:
        logger.warning("elasticsearch-py 未安装，ES 检索不可用")
        _es_last_failure = _time.monotonic()
        return None
    except Exception as e:
        logger.warning(f"Elasticsearch 连接失败（{_ES_COOLDOWN}s 内不再重试）: {e}")
        _es_last_failure = _time.monotonic()
        return None
    return _es_client


def _index_name(vector_db_id: int) -> str:
    return f"modelhub_kb_{vector_db_id}"


async def ensure_index(vector_db_id: int) -> bool:
    client = await get_es_client()
    if not client:
        return False

    index = _index_name(vector_db_id)
    try:
        if not await client.indices.exists(index=index):
            await client.indices.create(index=index, body={
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "analysis": {
                        "filter": {
                            "edu_synonyms": {
                                "type": "synonym",
                                "synonyms": [
                                    "毕设,毕业设计,毕设论文,毕业论文",
                                    "查重,论文查重,文本查重,查重检测,文本复制检测",
                                    "AIGC,AI生成内容,人工智能生成内容",
                                    "教务处,教务部",
                                    "选课,课程注册,选修",
                                    "绩点,GPA,学分绩点,平均绩点",
                                    "辅修,辅修专业,双学位",
                                    "保研,推免,推荐免试研究生",
                                    "考研,研究生入学考试",
                                    "四六级,CET,英语四六级,大学英语四六级",
                                    "奖学金,助学金,国家奖学金",
                                    "学籍,学籍信息,学籍变更",
                                    "转专业,专业调整",
                                    "补考,缓考,重修",
                                ],
                            },
                        },
                        "analyzer": {
                            "ik_smart_analyzer": {
                                "type": "custom",
                                "tokenizer": "ik_smart",
                                "filter": ["lowercase", "edu_synonyms"],
                            },
                            "ik_max_analyzer": {
                                "type": "custom",
                                "tokenizer": "ik_max_word",
                                "filter": ["lowercase", "edu_synonyms"],
                            },
                        },
                    },
                },
                "mappings": {
                    "properties": {
                        "content": {
                            "type": "text",
                            "analyzer": "ik_max_analyzer",
                            "search_analyzer": "ik_smart_analyzer",
                        },
                        "chunk_id": {"type": "keyword"},
                        "source": {"type": "keyword"},
                        "document_id": {"type": "keyword"},
                    }
                },
            })
            logger.info(f"ES 索引创建成功: {index}")
        return True
    except Exception as e:
        logger.warning(f"ES 索引创建失败 {index}: {e}")
        return False


async def index_chunks(
    vector_db_id: int,
    chunks: List[Dict],
) -> int:
    """批量写入 chunk 到 Elasticsearch（入库时调用）"""
    client = await get_es_client()
    if not client:
        return 0

    if not await ensure_index(vector_db_id):
        return 0

    index = _index_name(vector_db_id)
    operations = []
    for chunk in chunks:
        chunk_id = chunk.get("chunk_id", "")
        operations.append({"index": {"_index": index, "_id": chunk_id}})
        operations.append({
            "content": chunk.get("content", ""),
            "chunk_id": chunk_id,
            "source": chunk.get("source", ""),
            "document_id": str(chunk.get("document_id", "")),
        })

    if not operations:
        return 0

    try:
        resp = await client.bulk(body=operations, refresh=True)
        errors = resp.get("errors", False)
        if errors:
            error_count = sum(1 for item in resp["items"] if "error" in item.get("index", {}))
            logger.warning(f"ES 批量写入部分失败: {error_count}/{len(chunks)}")
        logger.info(f"ES 索引写入: index={index}, {len(chunks)} chunks")
        return len(chunks)
    except Exception as e:
        logger.warning(f"ES 批量写入失败: {e}")
        return 0


async def search(
    vector_db_id: int,
    query: str,
    n_results: int = 10,
) -> List[Dict]:
    """Elasticsearch BM25 全文检索"""
    client = await get_es_client()
    if not client:
        return []

    index = _index_name(vector_db_id)
    try:
        if not await client.indices.exists(index=index):
            return []

        resp = await client.search(
            index=index,
            body={
                "query": {
                    "match": {
                        "content": {
                            "query": query,
                            "analyzer": "ik_smart",
                        }
                    }
                },
                "size": n_results,
            },
        )

        results = []
        for hit in resp["hits"]["hits"]:
            results.append({
                "chunk_id": hit["_id"],
                "content": hit["_source"].get("content", ""),
                "score": hit["_score"],
                "source": hit["_source"].get("source", ""),
                "document_id": hit["_source"].get("document_id", ""),
            })
        return results
    except Exception as e:
        logger.warning(f"ES 检索失败: {e}")
        return []


async def delete_by_document(vector_db_id: int, document_id: str) -> int:
    """删除文档对应的所有 ES 索引"""
    client = await get_es_client()
    if not client:
        return 0

    index = _index_name(vector_db_id)
    try:
        resp = await client.delete_by_query(
            index=index,
            body={"query": {"term": {"document_id": str(document_id)}}},
        )
        deleted = resp.get("deleted", 0)
        logger.info(f"ES 删除: index={index}, document_id={document_id}, deleted={deleted}")
        return deleted
    except Exception as e:
        logger.warning(f"ES 删除失败: {e}")
        return 0


async def delete_index(vector_db_id: int) -> bool:
    """删除整个知识库的 ES 索引"""
    client = await get_es_client()
    if not client:
        return False

    index = _index_name(vector_db_id)
    try:
        if await client.indices.exists(index=index):
            await client.indices.delete(index=index)
            logger.info(f"ES 索引删除: {index}")
        return True
    except Exception as e:
        logger.warning(f"ES 索引删除失败: {e}")
        return False
