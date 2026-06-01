#!/usr/bin/env python3
"""
初始化默认智能对话配置。

该脚本可重复运行：如果默认知识库或默认模型配置已存在，会直接复用。
真实对话仍需要在供应商配置里填写对应 API Key。
"""
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database_async import AsyncSessionLocal, async_engine
from app.models.model_config import ModelConfig
from app.models.model_info import ModelInfo
from app.models.user import User
from app.models.vector_db import VectorDb
from app.utils.logger_config import get_logger

logger = get_logger(__name__)

DEFAULT_VECTOR_DB_NAME = "山东科技大学官方资料总库"
LEGACY_VECTOR_DB_NAMES = ["默认智能对话知识库"]
DEFAULT_CONFIG_SHARE_ID = "default-chat-config"
DEFAULT_CONFIG_NAME = "默认智能对话配置"


async def first_or_none(session, stmt):
    result = await session.execute(stmt)
    return result.scalars().first()


async def init_default_chat_config():
    async with AsyncSessionLocal() as db:
        admin = await first_or_none(
            db,
            select(User).where(User.email == "admin@example.com")
        )
        if not admin:
            raise RuntimeError("未找到 admin@example.com，请先运行 init_sample_data.py")

        embedding_model = await first_or_none(
            db,
            select(ModelInfo)
            .where(ModelInfo.type == "embedding")
            .order_by(ModelInfo.is_default.desc(), ModelInfo.priority.desc(), ModelInfo.id)
        )
        chat_model = None
        for model_name in ("qwen3.6-plus", "qwen-plus", "qwen-turbo"):
            chat_model = await first_or_none(
                db,
                select(ModelInfo)
                .where(ModelInfo.type == "chatllm", ModelInfo.model_name == model_name)
            )
            if chat_model:
                break
        if not chat_model:
            chat_model = await first_or_none(
                db,
                select(ModelInfo)
                .where(ModelInfo.type == "chatllm")
                .order_by(ModelInfo.is_default.desc(), ModelInfo.priority.desc(), ModelInfo.id)
            )
        if not embedding_model or not chat_model:
            raise RuntimeError("未找到基础模型信息，请先运行 init_provider_and_models.py")

        vector_db = await first_or_none(
            db,
            select(VectorDb).where(VectorDb.name == DEFAULT_VECTOR_DB_NAME)
        )
        if not vector_db:
            vector_db = await first_or_none(
                db,
                select(VectorDb).where(VectorDb.name.in_(LEGACY_VECTOR_DB_NAMES))
            )
            if vector_db:
                vector_db.name = DEFAULT_VECTOR_DB_NAME
                vector_db.describe = "山东科技大学官网、教务处、研究生院及学院官网等公开权威资料总库"
                vector_db.scope = "public"
                await db.flush()
                logger.info("旧默认知识库已升级为官方资料总库: ID=%s", vector_db.id)
        if not vector_db:
            vector_db = VectorDb(
                user_id=admin.id,
                embedding_id=embedding_model.id,
                name=DEFAULT_VECTOR_DB_NAME,
                describe="山东科技大学官网、教务处、研究生院及学院官网等公开权威资料总库。",
                organization_id=admin.school_id,
                school_id=admin.school_id,
                scope="public",
                access_level="school",
            )
            db.add(vector_db)
            await db.flush()
            logger.info("创建默认知识库: %s (ID: %s)", vector_db.name, vector_db.id)
        else:
            logger.info("默认知识库已存在: %s (ID: %s)", vector_db.name, vector_db.id)

        config = await first_or_none(
            db,
            select(ModelConfig).where(ModelConfig.share_id == DEFAULT_CONFIG_SHARE_ID)
        )
        if not config:
            config = ModelConfig(
                user_id=admin.id,
                share_id=DEFAULT_CONFIG_SHARE_ID,
                base_model_id=chat_model.id,
                name=DEFAULT_CONFIG_NAME,
                temperature=0.70,
                top_p=0.80,
                prompt="你是面向毕业设计知识库系统的智能助手，回答要清晰、准确、简洁。",
                describe="本地联调默认公开配置。若对话提示 API Key 为空，请先配置供应商密钥。",
                organization_id=admin.school_id,
                school_id=admin.school_id,
                scope="public",
                is_private=False,
            )
            db.add(config)
            await db.flush()
            logger.info("创建默认模型配置: %s (ID: %s)", config.name, config.id)
        else:
            config.base_model_id = chat_model.id
            config.name = f"{DEFAULT_CONFIG_NAME}（{chat_model.model_name}）"
            config.describe = f"本地联调默认公开配置，使用 {chat_model.model_name}。"
            await db.flush()
            logger.info("默认模型配置已存在: %s (ID: %s)", config.name, config.id)

        await db.commit()
        logger.info("默认智能对话配置初始化完成。模型: %s", chat_model.model_name)


async def main():
    try:
        await init_default_chat_config()
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
