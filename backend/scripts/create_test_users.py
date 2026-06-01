"""
创建测试用户脚本
快速创建管理员、教师、学生测试账号
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
from app.utils.JwtUtil import get_password_hash
from app.utils.async_db import AsyncDB
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


# 测试用户配置
TEST_USERS = [
    {
        "name": "测试管理员",
        "email": "test_admin@example.com",
        "password": "admin123",
        "role": "admin",
        "describe": "测试管理员账号"
    },
    {
        "name": "测试教师",
        "email": "test_teacher@edu.com",
        "password": "teacher123",
        "role": "teacher",
        "describe": "测试教师账号"
    },
    {
        "name": "测试学生",
        "email": "test_student@gmail.com",
        "password": "student123",
        "role": "student",
        "describe": "测试学生账号"
    }
]


async def create_test_users():
    """创建测试用户"""
    logger.info("="*80)
    logger.info("创建测试用户")
    logger.info("="*80)

    async with AsyncSessionLocal() as session:
        created_count = 0
        updated_count = 0

        for user_config in TEST_USERS:
            # 检查用户是否已存在
            result = await session.execute(
                select(User).where(User.email == user_config["email"])
            )
            existing_user = result.scalar_one_or_none()

            if existing_user:
                # 更新现有用户的角色和密码
                logger.info(f"\n⚠️  用户已存在: {user_config['email']}")
                logger.info(f"   更新角色为: {user_config['role']}")
                logger.info(f"   重置密码为: {user_config['password']}")

                existing_user.role = user_config["role"]
                existing_user.password = get_password_hash(user_config["password"])
                existing_user.status = "active"

                await AsyncDB.update(session, existing_user)
                await AsyncDB.commit(session)
                updated_count += 1

            else:
                # 创建新用户
                logger.info(f"\n✅ 创建新用户: {user_config['email']}")

                new_user = User(
                    name=user_config["name"],
                    email=user_config["email"],
                    password=get_password_hash(user_config["password"]),
                    role=user_config["role"],
                    describe=user_config["describe"],
                    status="active"
                )

                await AsyncDB.create(session, new_user)
                await AsyncDB.commit(session)
                created_count += 1

        logger.info("\n" + "="*80)
        logger.info("创建完成！")
        logger.info("="*80)
        logger.info(f"\n新创建: {created_count} 个用户")
        logger.info(f"已更新: {updated_count} 个用户")

        logger.info("\n📋 测试账号列表:")
        logger.info("-" * 80)

        for user_config in TEST_USERS:
            logger.info(f"\n角色: {user_config['role'].upper()}")
            logger.info(f"  邮箱: {user_config['email']}")
            logger.info(f"  密码: {user_config['password']}")
            logger.info(f"  姓名: {user_config['name']}")

        logger.info("\n" + "="*80)
        logger.info("\n🚀 下一步:")
        logger.info("  1. 打开浏览器: http://localhost:5174/")
        logger.info("  2. 使用上面的账号登录测试")
        logger.info("  3. 查看浏览器控制台确认角色")
        logger.info("\n" + "="*80)


if __name__ == "__main__":
    asyncio.run(create_test_users())
