"""
创建测试数据脚本
快速创建模型配置和向量数据库用于测试
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database_async import AsyncSessionLocal
from app.models.user import User
from app.models.model_config import ModelConfig
from app.models.vector_db import VectorDb
from app.models.model_info import ModelInfo
from app.utils.async_db import AsyncDB
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


async def create_test_model_config():
    """创建测试模型配置"""
    logger.info("="*80)
    logger.info("创建测试模型配置")
    logger.info("="*80)

    async with AsyncSessionLocal() as session:
        # 获取一个可用的模型
        result = await session.execute(select(ModelInfo).limit(1))
        model = result.scalar_one_or_none()

        if not model:
            logger.error("❌ 没有找到可用的模型！请先在数据库中添加模型信息。")
            logger.info("\n提示：运行以下 SQL 添加测试模型：")
            logger.info("INSERT INTO model_info (id, name, api_address, api_key, type) VALUES")
            logger.info("  (1, '测试模型', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'your-api-key', 'chatllm');")
            return False

        # 检查是否已有配置
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.name == "默认测试配置")
        )
        existing_config = result.scalar_one_or_none()

        if existing_config:
            logger.info(f"✅ 配置已存在: {existing_config.name} (ID: {existing_config.id})")
            logger.info(f"\n配置ID: {existing_config.id}")
            logger.info("你可以直接使用这个配置ID进行对话测试")
            return existing_config.id

        # 创建新配置
        logger.info(f"\n使用模型: {model.name} (ID: {model.id})")

        new_config = ModelConfig(
            user_id=1,  # 假设管理员用户ID为1
            share_id="test_config_001",
            base_model_id=model.id,
            name="默认测试配置",
            temperature=0.7,
            top_p=0.9,
            prompt="你是一个有用的AI助手。",
            describe="用于测试的默认对话配置",
            vector_db_id=None,  # 暂时不关联向量数据库
            organization_id=None,
            school_id=None,
            scope="public",
            is_private=False
        )

        try:
            await AsyncDB.create(session, new_config)
            await AsyncDB.commit(session)

            logger.info("\n✅ 成功创建模型配置！")
            logger.info(f"\n配置详情:")
            logger.info(f"  ID: {new_config.id}")
            logger.info(f"  名称: {new_config.name}")
            logger.info(f"  模型: {model.name}")
            logger.info(f"  Temperature: {new_config.temperature}")
            logger.info(f"  Top P: {new_config.top_p}")
            logger.info(f"  可见性: {new_config.scope}")

            logger.info("\n🚀 现在可以使用这个配置ID进行对话了！")
            logger.info(f"   配置ID: {new_config.id}")

            return new_config.id

        except Exception as e:
            logger.error(f"\n❌ 创建配置失败: {str(e)}")
            await AsyncDB.rollback(session)
            return False


async def list_available_configs():
    """列出所有可用的配置"""
    logger.info("\n" + "="*80)
    logger.info("现有模型配置列表")
    logger.info("="*80)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ModelConfig))
        configs = result.scalars().all()

        if not configs:
            logger.warning("⚠️  系统中没有任何模型配置")
            logger.info("\n你需要先创建模型配置才能进行对话")
            return []

        logger.info(f"\n找到 {len(configs)} 个配置:\n")

        for config in configs:
            logger.info(f"📋 配置 ID: {config.id}")
            logger.info(f"   名称: {config.name}")
            logger.info(f"   创建者: user_id={config.user_id}")
            logger.info(f"   可见性: {config.scope}")
            logger.info(f"   向量数据库: {config.vector_db_id or '未关联'}")
            logger.info("")

        return [c.id for c in configs]


async def main():
    """主函数"""
    # 先列出现有配置
    config_ids = await list_available_configs()

    if not config_ids:
        # 没有配置，创建一个
        config_id = await create_test_model_config()
        if not config_id:
            logger.error("\n❌ 无法创建测试配置，对话功能不可用")
            logger.info("\n建议操作：")
            logger.info("1. 在数据库中添加模型信息（model_info 表）")
            logger.info("2. 或者在浏览器中访问模型配置页面创建")
            return
    else:
        logger.info(f"\n✅ 可以使用以下配置ID进行对话: {config_ids}")

    logger.info("\n" + "="*80)
    logger.info("测试对话配置完成！")
    logger.info("="*80)
    logger.info("\n下一步：")
    logger.info("1. 刷新浏览器页面")
    logger.info("2. 在对话页面选择一个模型配置")
    logger.info("3. 开始对话测试")
    logger.info("="*80)


if __name__ == "__main__":
    asyncio.run(main())
