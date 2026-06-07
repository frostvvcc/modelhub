"""
元数据回填脚本

对已经入库到 ChromaDB 的文档 chunk 补充结构化元数据（院系、分类、日期）。

三级元数据来源：
1. MySQL document 表的 name 字段 → 匹配 metadata_mapping.json 的 filename
2. metadata_mapping.json 中的 URL 元数据 → 发布日期
3. chunk 文本内容 → 正则提取年份（fallback）

用法：
    python scripts/backfill_metadata.py
    python scripts/backfill_metadata.py --vector-db-id 10
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_SCRIPT_DIR = Path(__file__).resolve().parent
METADATA_MAPPING_PATH = _SCRIPT_DIR / "metadata_mapping.json"

_DATE_IN_TEXT_RE = re.compile(r'(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})')
_YEAR_IN_TEXT_RE = re.compile(r'(\d{4})\s*年\s*\d{1,2}\s*月')


def load_metadata_mapping() -> dict:
    if not METADATA_MAPPING_PATH.exists():
        print(f"[WARN] 元数据映射文件不存在: {METADATA_MAPPING_PATH}")
        return {"file_metadata": {}, "url_metadata": {}}
    with open(METADATA_MAPPING_PATH, "r") as f:
        return json.load(f)


def build_name_to_meta(file_meta: dict) -> dict:
    """构建 {filename → metadata} 的快速查找表"""
    lookup = {}
    for key, meta in file_meta.items():
        fname = meta.get("filename", "")
        if fname:
            lookup[fname] = meta
    return lookup


def load_document_mapping(db_password: str) -> dict:
    """从 MySQL 加载 {document_id → document_name} 映射"""
    try:
        import pymysql
        conn = pymysql.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USERNAME", "root"),
            password=db_password,
            database=os.getenv("DB_DATABASE", "modelhub"),
        )
        cur = conn.cursor()
        cur.execute("SELECT id, name, original_name FROM document WHERE is_folder=0")
        mapping = {}
        for row in cur.fetchall():
            doc_id = str(row[0])
            name = row[1] or ""
            original = row[2] or name
            mapping[doc_id] = {"name": name, "original_name": original}
        conn.close()
        print(f"[INFO] MySQL: 加载 {len(mapping)} 个文档映射")
        return mapping
    except Exception as e:
        print(f"[WARN] MySQL 不可用，跳过文档映射: {e}")
        return {}


def extract_year_from_text(text: str) -> str:
    match = _DATE_IN_TEXT_RE.search(text[:500])
    if match:
        year = match.group(1)
        if 1990 <= int(year) <= 2030:
            return year
    match = _YEAR_IN_TEXT_RE.search(text[:500])
    if match:
        year = match.group(1)
        if 1990 <= int(year) <= 2030:
            return year
    return ""


def backfill_collection(
    client,
    collection_name: str,
    name_lookup: dict,
    doc_mapping: dict,
    url_meta: dict,
    chroma_port: int,
):
    try:
        collection = client.get_collection(name=collection_name)
    except Exception as e:
        print(f"  [SKIP] {collection_name}: {e}")
        return 0

    total = collection.count()
    if total == 0:
        print(f"  [SKIP] {collection_name}: empty")
        return 0

    # 分批获取（ChromaDB 单次 get 有限制）
    batch_size = 500
    updated_total = 0

    for offset in range(0, total, batch_size):
        data = collection.get(
            limit=batch_size,
            offset=offset,
            include=["documents", "metadatas"],
        )
        ids = data.get("ids", [])
        docs = data.get("documents", [])
        metas = data.get("metadatas", [])

        update_ids = []
        update_metas = []

        for i, (chunk_id, doc, meta) in enumerate(zip(ids, docs, metas)):
            meta = meta or {}

            # 已有完整元数据，跳过
            if meta.get("department") and meta.get("publish_year"):
                continue

            new_meta = dict(meta)
            changed = False

            # 1. 通过 document_id → MySQL name → metadata_mapping 查找院系
            doc_id = str(meta.get("document_id", ""))
            if doc_id and doc_id in doc_mapping and not meta.get("department"):
                doc_name = doc_mapping[doc_id].get("original_name") or doc_mapping[doc_id].get("name", "")
                if doc_name in name_lookup:
                    found = name_lookup[doc_name]
                    if found.get("department"):
                        new_meta["department"] = found["department"]
                        changed = True
                    if found.get("category") and not meta.get("category"):
                        new_meta["category"] = found["category"]
                        changed = True

            # 2. 直接从 source 文件名尝试匹配（去掉 UUID 前缀）
            if not new_meta.get("department"):
                source = meta.get("source", "")
                # source 格式: UUID_原始文件名.txt
                parts = source.split("_", 1)
                if len(parts) == 2:
                    original_fname = parts[1]
                    if original_fname in name_lookup:
                        found = name_lookup[original_fname]
                        if found.get("department"):
                            new_meta["department"] = found["department"]
                            changed = True
                        if found.get("category") and not meta.get("category"):
                            new_meta["category"] = found["category"]
                            changed = True

            # 3. 从文本内容提取年份
            if not new_meta.get("publish_year") and doc:
                year = extract_year_from_text(doc)
                if year:
                    new_meta["publish_year"] = year
                    changed = True

            if changed:
                update_ids.append(chunk_id)
                update_metas.append(new_meta)

        if update_ids:
            # 分小批更新
            for j in range(0, len(update_ids), 100):
                batch_ids = update_ids[j:j+100]
                batch_metas = update_metas[j:j+100]
                collection.update(ids=batch_ids, metadatas=batch_metas)
            updated_total += len(update_ids)

    print(f"  [OK] {collection_name}: {updated_total}/{total} chunks updated")
    return updated_total


def main():
    parser = argparse.ArgumentParser(description="ChromaDB 元数据回填")
    parser.add_argument("--vector-db-id", type=int, help="指定知识库 ID")
    parser.add_argument("--chroma-port", type=int, default=8000)
    parser.add_argument("--db-password", type=str, default=None)
    args = parser.parse_args()

    # 加载元数据映射
    mapping = load_metadata_mapping()
    file_meta = mapping.get("file_metadata", {})
    url_meta = mapping.get("url_metadata", {})
    name_lookup = build_name_to_meta(file_meta)
    print(f"[INFO] 元数据映射: {len(name_lookup)} 文件名")

    # 从 .env 读取密码
    db_password = args.db_password
    if not db_password:
        env_file = Path(__file__).resolve().parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().split("\n"):
                if line.startswith("DB_PASSWORD="):
                    db_password = line.split("=", 1)[1].strip()
                    break

    # 加载 MySQL 文档映射
    doc_mapping = load_document_mapping(db_password) if db_password else {}

    # 连接 ChromaDB
    import chromadb
    try:
        client = chromadb.HttpClient(host="127.0.0.1", port=args.chroma_port)
        client.heartbeat()
        print(f"[INFO] ChromaDB connected on port {args.chroma_port}")
    except Exception as e:
        print(f"[ERROR] ChromaDB connection failed: {e}")
        sys.exit(1)

    if args.vector_db_id:
        total = backfill_collection(
            client, f"vector_db_{args.vector_db_id}",
            name_lookup, doc_mapping, url_meta, args.chroma_port,
        )
    else:
        collections = client.list_collections()
        total = 0
        for col in collections:
            name = col.name if hasattr(col, "name") else str(col)
            if name.startswith("vector_db_"):
                total += backfill_collection(
                    client, name, name_lookup, doc_mapping, url_meta, args.chroma_port,
                )

    print(f"\n[DONE] Total: {total} chunks updated")


if __name__ == "__main__":
    main()
