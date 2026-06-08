"""
GraphRAG 图谱增强检索模块

文档入库时用 LLM 从 chunk 中抽取三元组（实体-关系-实体），存入 Neo4j。
检索时从 query 提取关键实体 → Cypher 查询 1-2 跳子图 → 三元组注入 prompt。

典型场景：学生问"从计算机学院转到电气学院需要什么条件"，
图谱把分散在不同文档的实体关系串起来，一次查询拿到完整答案。
"""
import os
import json
import asyncio
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)

from app.config import settings as _settings

NEO4J_ENABLED = _settings.neo4j_enabled
NEO4J_URI = _settings.neo4j_uri
NEO4J_USER = _settings.neo4j_user
NEO4J_PASSWORD = _settings.neo4j_password

_driver = None
_llm_client: Optional[AsyncOpenAI] = None


def _get_driver():
    global _driver
    if _driver is None and NEO4J_ENABLED:
        try:
            from neo4j import GraphDatabase
            _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            _driver.verify_connectivity()
            logger.info(f"Neo4j 连接成功: {NEO4J_URI}")
        except Exception as e:
            logger.warning(f"Neo4j 连接失败: {e}")
            _driver = None
    return _driver


def _get_llm_client() -> AsyncOpenAI:
    global _llm_client
    if _llm_client is None:
        import httpx
        _llm_client = AsyncOpenAI(
            api_key=settings.rag_llm_api_key or settings.embedding_api_key,
            base_url=settings.rag_llm_base_url or settings.embedding_base_url,
            timeout=httpx.Timeout(timeout=60.0, connect=10.0, read=50.0, write=10.0),
            max_retries=1,
        )
    return _llm_client


@dataclass
class Triple:
    subject: str
    relation: str
    obj: str
    source_chunk_id: str = ""
    document_id: str = ""


async def extract_triples(
    text: str,
    chunk_id: str = "",
    document_id: str = "",
    model: str = None,
) -> List[Triple]:
    """用 LLM 从文本块中抽取三元组"""
    model = model or settings.rag_llm_model
    client = _get_llm_client()
    prompt = (
        "从以下文本中抽取实体和关系三元组。\n\n"
        "规则：\n"
        "1. 三元组格式：[主语, 关系, 宾语]\n"
        "2. 实体使用规范名称（如'计算机科学与技术学院'而非'计院'）\n"
        "3. 关系使用动词短语（如'要求''截止于''属于'）\n"
        "4. 只提取文本中明确表述的事实，不推断\n"
        "5. 只输出 JSON 数组，格式：[[\"主语\", \"关系\", \"宾语\"], ...]\n\n"
        f"文本：\n{text[:2000]}\n\n三元组："
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip()

        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start < 0 or end <= start:
            return []

        data = json.loads(raw[start:end])
        triples = []
        for item in data:
            if isinstance(item, list) and len(item) >= 3:
                triples.append(Triple(
                    subject=str(item[0]).strip(),
                    relation=str(item[1]).strip(),
                    obj=str(item[2]).strip(),
                    source_chunk_id=chunk_id,
                    document_id=document_id,
                ))

        logger.info(f"三元组抽取: chunk={chunk_id}, 提取 {len(triples)} 条")
        return triples
    except Exception as e:
        logger.error(f"三元组抽取失败: {e}")
        return []


def store_triples(triples: List[Triple], vector_db_id: int) -> int:
    """将三元组批量写入 Neo4j"""
    driver = _get_driver()
    if not driver or not triples:
        return 0

    count = 0
    with driver.session() as session:
        for t in triples:
            try:
                session.run(
                    """
                    MERGE (s:Entity {name: $subject, kb_id: $kb_id})
                    MERGE (o:Entity {name: $object, kb_id: $kb_id})
                    MERGE (s)-[r:RELATION {type: $relation}]->(o)
                    ON CREATE SET r.source_chunk_ids = [$chunk_id],
                                  r.document_id = $doc_id,
                                  r.kb_id = $kb_id
                    ON MATCH SET r.source_chunk_ids = CASE
                        WHEN NOT $chunk_id IN coalesce(r.source_chunk_ids, [])
                        THEN coalesce(r.source_chunk_ids, []) + $chunk_id
                        ELSE r.source_chunk_ids END
                    """,
                    subject=t.subject,
                    object=t.obj,
                    relation=t.relation,
                    chunk_id=t.source_chunk_id,
                    doc_id=t.document_id,
                    kb_id=str(vector_db_id),
                )
                count += 1
            except Exception as e:
                logger.warning(f"Neo4j 写入失败: {t.subject}-{t.relation}-{t.obj}: {e}")

    logger.info(f"Neo4j 写入完成: {count}/{len(triples)} 条三元组, kb_id={vector_db_id}")
    return count


async def extract_query_entities(
    query: str,
    model: str = None,
) -> List[str]:
    """从用户查询中提取关键实体"""
    model = model or settings.rag_llm_model
    client = _get_llm_client()
    prompt = (
        "从以下问题中提取关键实体名词（人名、机构名、政策名、课程名等）。\n"
        "只输出 JSON 数组，如 [\"计算机学院\", \"转专业\"]。\n\n"
        f"问题：{query}\n\n实体："
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip()
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            entities = json.loads(raw[start:end])
            return [str(e).strip() for e in entities if isinstance(e, str) and e.strip()]
    except Exception as e:
        logger.error(f"查询实体提取失败: {e}")
    return []


def query_subgraph(
    entities: List[str],
    vector_db_id: int,
    max_hops: int = 2,
    limit: int = 30,
) -> List[Dict[str, str]]:
    """从 Neo4j 查询实体的 1-2 跳子图，返回三元组列表"""
    driver = _get_driver()
    if not driver or not entities:
        return []

    kb_id = str(vector_db_id)
    triples = []

    with driver.session() as session:
        for entity in entities[:5]:
            try:
                result = session.run(
                    """
                    MATCH path = (s:Entity {kb_id: $kb_id})-[r:RELATION*1..""" + str(max_hops) + """]->(o:Entity {kb_id: $kb_id})
                    WHERE s.name CONTAINS $entity OR o.name CONTAINS $entity
                    UNWIND relationships(path) AS rel
                    WITH startNode(rel) AS src, rel, endNode(rel) AS tgt
                    RETURN src.name AS subject, rel.type AS relation, tgt.name AS object
                    LIMIT $limit
                    """,
                    entity=entity,
                    kb_id=kb_id,
                    limit=limit,
                )
                for record in result:
                    triples.append({
                        "subject": record["subject"],
                        "relation": record["relation"],
                        "object": record["object"],
                    })
            except Exception as e:
                logger.warning(f"Neo4j 子图查询失败 entity={entity}: {e}")

    seen = set()
    deduped = []
    for t in triples:
        key = (t["subject"], t["relation"], t["object"])
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    logger.info(f"图谱子图查询: entities={entities}, 返回 {len(deduped)} 条三元组")
    return deduped[:limit]


def format_triples_for_context(triples: List[Dict[str, str]]) -> str:
    """将三元组格式化为 LLM 上下文注入文本"""
    if not triples:
        return ""
    lines = [f"- {t['subject']} → {t['relation']} → {t['object']}" for t in triples]
    return "【知识图谱先验】\n" + "\n".join(lines)


async def graph_augmented_retrieval(
    query: str,
    vector_db_id: int,
) -> List[Dict[str, str]]:
    """GraphRAG 检索流程：返回三元组列表（供 RRF 三路融合使用）"""
    if not NEO4J_ENABLED or not _get_driver():
        return []

    entities = await extract_query_entities(query)
    if not entities:
        return []

    return await asyncio.to_thread(query_subgraph, entities, vector_db_id)


async def graph_augmented_context(
    query: str,
    vector_db_id: int,
) -> str:
    """完整的 GraphRAG 检索流程：query→实体提取→子图查询→格式化上下文"""
    triples = await graph_augmented_retrieval(query, vector_db_id)
    return format_triples_for_context(triples)


def delete_graph_by_document(vector_db_id: int, document_id: str) -> int:
    """删除文档对应的所有图谱三元组"""
    driver = _get_driver()
    if not driver:
        return 0

    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH ()-[r:RELATION {kb_id: $kb_id, document_id: $doc_id}]->()
                DELETE r
                RETURN count(r) AS deleted
                """,
                kb_id=str(vector_db_id),
                doc_id=str(document_id),
            )
            deleted = result.single()["deleted"]
            logger.info(f"图谱删除: document_id={document_id}, 删除 {deleted} 条关系")
            return deleted
    except Exception as e:
        logger.warning(f"图谱删除失败: document_id={document_id}: {e}")
        return 0
