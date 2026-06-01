#!/usr/bin/env python3
"""
创建数据库表
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import inspect, text
from app.database_async import async_engine
from app.extensions import Base
from app.models import *  # 导入所有模型以注册表


async def ensure_column(conn, table_name: str, column_name: str, ddl: str) -> None:
    """create_all 不会修改旧表，这里补充轻量字段迁移。"""
    def has_column(sync_conn):
        inspector = inspect(sync_conn)
        return column_name in {column["name"] for column in inspector.get_columns(table_name)}

    exists = await conn.run_sync(has_column)
    if not exists:
        await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))
        print(f"✅ 已补充字段: {table_name}.{column_name}")


async def create_tables():
    """创建所有数据库表"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_column(conn, "model_config", "prompt_variables", "prompt_variables TEXT NULL")
        await ensure_column(conn, "model_config", "knowledge_context_template", "knowledge_context_template TEXT NULL")
        await ensure_column(conn, "model_config", "citation_template", "citation_template VARCHAR(100) NULL DEFAULT '[来源{index}]'")
        await ensure_column(conn, "model_config", "refusal_strategy", "refusal_strategy TEXT NULL")
        await ensure_column(conn, "model_config", "max_context_chars", "max_context_chars INTEGER NOT NULL DEFAULT 6000")
        await ensure_column(conn, "model_config", "answer_with_citations", "answer_with_citations BOOLEAN NOT NULL DEFAULT TRUE")
        await ensure_column(conn, "document", "status", "status VARCHAR(20) NOT NULL DEFAULT 'success'")
        await ensure_column(conn, "document", "error_message", "error_message TEXT NULL")
        await ensure_column(conn, "document", "archived_at", "archived_at DATETIME NULL")
        await ensure_column(conn, "bot", "school_id", "school_id INTEGER NULL")
        await ensure_column(conn, "message", "metadata_json", "metadata_json TEXT NULL")
    print("✅ 数据库表创建成功")


if __name__ == "__main__":
    asyncio.run(create_tables())
