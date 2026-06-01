"""
Bot CRUD mapper（异步）
"""
from typing import List, Optional, Set, Union
from sqlalchemy import select, update, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.bot import Bot


class AsyncBotMapper:

    @staticmethod
    async def create(db: AsyncSession, **kwargs) -> Bot:
        bot = Bot(**kwargs)
        db.add(bot)
        await db.commit()
        await db.refresh(bot)
        return await AsyncBotMapper.get_by_id(db, bot.id)

    @staticmethod
    async def get_by_id(db: AsyncSession, bot_id: int) -> Optional[Bot]:
        result = await db.execute(
            select(Bot).options(selectinload(Bot.user), selectinload(Bot.organization)).where(Bot.id == bot_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_user(db: AsyncSession, user_id: int) -> List[Bot]:
        result = await db.execute(
            select(Bot).options(selectinload(Bot.user), selectinload(Bot.organization))
            .where(Bot.user_id == user_id).order_by(Bot.created_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def get_all(db: AsyncSession) -> List[Bot]:
        result = await db.execute(
            select(Bot).options(selectinload(Bot.user), selectinload(Bot.organization))
            .order_by(Bot.created_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def get_accessible(
        db: AsyncSession,
        user_id: int,
        org_ids: Optional[Union[int, list[int]]] = None,
        teaching_space_bot_ids: Optional[Set[int]] = None,
    ) -> List[Bot]:
        """返回用户可见的 Bot（自己的 + 组织的 + 教学空间的）"""
        conditions = [Bot.user_id == user_id]
        if org_ids:
            ids = org_ids if isinstance(org_ids, list) else [org_ids]
            conditions.append(Bot.organization_id.in_(ids))
        if teaching_space_bot_ids:
            conditions.append(Bot.id.in_(teaching_space_bot_ids))
        result = await db.execute(
            select(Bot).options(selectinload(Bot.user), selectinload(Bot.organization))
            .where(or_(*conditions)).order_by(Bot.created_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def update(db: AsyncSession, bot_id: int, **kwargs) -> Optional[Bot]:
        await db.execute(update(Bot).where(Bot.id == bot_id).values(**kwargs))
        await db.commit()
        return await AsyncBotMapper.get_by_id(db, bot_id)

    @staticmethod
    async def delete(db: AsyncSession, bot_id: int) -> bool:
        from app.models.teaching_space import TeachingSpaceResource
        await db.execute(
            delete(TeachingSpaceResource).where(
                TeachingSpaceResource.resource_type == "bot",
                TeachingSpaceResource.resource_id == bot_id
            )
        )
        result = await db.execute(delete(Bot).where(Bot.id == bot_id))
        await db.commit()
        return result.rowcount > 0
