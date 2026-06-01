#!/usr/bin/env python3
"""
为官方资料总库写入本地演示资料并完成向量化。

资料只用于本地联调和毕业设计演示，不代表学校正式制度。
"""
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database_async import AsyncSessionLocal, async_engine
from app.models.document import Document
from app.models.model_info import ModelInfo
from app.models.provider_config import ProviderConfig
from app.models.user import User
from app.models.vector_db import VectorDb
from app.services.vector_service import AsyncVectorService
from app.utils.async_db import AsyncDB
from app.utils.logger_config import get_logger

logger = get_logger(__name__)

VECTOR_DB_NAME = "山东科技大学官方资料总库"
LEGACY_VECTOR_DB_NAMES = ["默认智能对话知识库"]
BASE_DOCS_DIR = project_root / "data" / "knowledge_sources"

DEMO_DOCUMENTS = {
    "毕业论文查重与AIGC检测说明-演示.txt": """本文件为 ModelHub 本地演示资料，不代表山东科技大学或任何学院的正式制度。学生毕业设计、论文查重、AIGC 检测要求应以学校教务处、学院或导师发布的最新通知为准。

在本演示系统中，智能对话可以回答毕业设计相关流程问题，也可以结合已上传的制度文件、论文写作指南、查重说明等知识库资料生成回答。

关于查重系统：实际学校可能使用中国知网、维普、万方或学校采购的其他检测平台。管理员可以在知识库中上传正式通知，并在回答中引用这些通知。

关于 AIGC 检测：实际要求可能包括检测工具、检测比例、申诉流程、导师审核和学院复核等环节。演示系统只提供问答和资料检索能力，不替代学校正式判定。

建议回答方式：如果知识库没有正式通知，应提示“请以学校或学院最新通知为准”，并说明当前回答基于演示资料。""",
    "ModelHub知识库使用说明-演示.txt": """ModelHub 的知识库流程包括：创建知识库、上传文档、文档解析、文本切块、生成向量、写入 ChromaDB、在智能对话中检索相关片段。

模型配置可以关联一个知识库。用户发起对话时，系统会先按模型配置找到关联知识库，再进行向量检索和 BM25 检索，最后把检索到的片段注入大模型上下文。

如果知识库没有文档，智能对话会退化为通用大模型回答；如果知识库有相关文档，回答会显示知识库来源和相似度。""",
    "毕业设计问答示例资料-演示.txt": """毕业设计常见问题包括：选题确认、任务书提交、开题报告、中期检查、论文撰写、论文查重、答辩资格审核、最终答辩和归档。

学生提问“毕设论文查重用什么系统”时，如果知识库中没有学校正式通知，应回答：当前演示资料无法确认学校实际采购或指定的平台，请以学院或教务处通知为准。系统管理员可以上传正式查重通知，让回答基于知识库引用。

学生提问“AIGC 检测怎么处理”时，应提醒：AIGC 检测规则属于学校管理要求，具体阈值、工具和处置流程以最新通知为准。""",
}


async def first_or_none(session, stmt):
    result = await session.execute(stmt)
    return result.scalars().first()


async def ensure_aliyun_embedding_model(session) -> ModelInfo:
    provider = await first_or_none(
        session,
        select(ProviderConfig).where(ProviderConfig.code == "aliyun")
    )
    if not provider:
        raise RuntimeError("未找到阿里云通义千问供应商配置")

    model = await first_or_none(
        session,
        select(ModelInfo).where(ModelInfo.model_name == "text-embedding-v3")
    )
    if model:
        model.provider_id = provider.id
        model.type = "embedding"
        model.is_active = True
        model.priority = max(model.priority or 0, 92)
        await AsyncDB.update(session, model)
        return model

    model = ModelInfo(
        model_name="text-embedding-v3",
        type="embedding",
        provider_id=provider.id,
        model_endpoint="/embeddings",
        describe="阿里云文本嵌入模型 v3，用于本地知识库向量化",
        version="text-embedding-v3",
        max_tokens=None,
        context_window=8192,
        is_active=True,
        is_default=False,
        priority=92,
    )
    model = await AsyncDB.create(session, model)
    return model


async def seed_default_knowledge_base():
    async with AsyncSessionLocal() as db:
        admin = await first_or_none(db, select(User).where(User.email == "admin@example.com"))
        if not admin:
            raise RuntimeError("未找到 admin@example.com，请先运行 init_sample_data.py")

        vector_db = await first_or_none(db, select(VectorDb).where(VectorDb.name == VECTOR_DB_NAME))
        if not vector_db:
            vector_db = await first_or_none(db, select(VectorDb).where(VectorDb.name.in_(LEGACY_VECTOR_DB_NAMES)))
        if not vector_db:
            raise RuntimeError("未找到山东科技大学官方资料总库，请先运行 init_default_chat_config.py")

        embedding_model = await ensure_aliyun_embedding_model(db)
        vector_db.embedding_id = embedding_model.id
        await AsyncDB.update(db, vector_db)
        await AsyncDB.commit(db)

        await AsyncVectorService.ensure_collection_exists(vector_db.id)

        save_dir = BASE_DOCS_DIR / f"vector_db_{vector_db.id}"
        save_dir.mkdir(parents=True, exist_ok=True)

        created = 0
        vectorized = 0
        for filename, content in DEMO_DOCUMENTS.items():
            existing = await first_or_none(
                db,
                select(Document).where(
                    Document.vector_db_id == vector_db.id,
                    Document.name == filename,
                )
            )
            if existing:
                logger.info("文档已存在，跳过: %s", filename)
                continue

            file_path = save_dir / filename
            file_path.write_text(content, encoding="utf-8")

            document = Document(
                vector_db_id=vector_db.id,
                user_id=admin.id,
                name=filename,
                original_name=filename,
                type="txt",
                size=file_path.stat().st_size,
                save_path=str(file_path.relative_to(project_root)),
                describe="本地联调演示资料",
                parent_id=None,
                is_folder=False,
                folder_path=None,
            )
            document = await AsyncDB.create(db, document)
            await AsyncDB.commit(db)
            created += 1

            await asyncio.to_thread(
                AsyncVectorService._process_and_add_file,
                vector_db.id,
                str(file_path),
                document.id,
            )
            vectorized += 1
            logger.info("文档已向量化: %s", filename)

        logger.info(
            "默认知识库准备完成: vector_db_id=%s, 新增文档=%s, 新向量化=%s",
            vector_db.id,
            created,
            vectorized,
        )


async def main():
    try:
        await seed_default_knowledge_base()
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
