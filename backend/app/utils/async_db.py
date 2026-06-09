"""
异步数据库工具 — 带分页支持 + 安全硬上限

- get_all / filter_by 加入 limit/offset 参数
- 硬上限 1000 条兜底（即使调用方忘记传分页参数）
- 新增 paginate() 方法支持 Keyset Pagination
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_
from typing import Type, TypeVar, Optional, List, Any, Tuple
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')

_HARD_LIMIT = 1000


class AsyncDB:
    """异步数据库操作工具类"""

    @staticmethod
    async def get_by_id(session: AsyncSession, model: Type[T], id: int) -> Optional[T]:
        return await session.get(model, id)

    @staticmethod
    async def get_by_field(
        session: AsyncSession,
        model: Type[T],
        field_name: str,
        field_value: Any,
    ) -> Optional[T]:
        field = getattr(model, field_name)
        stmt = select(model).where(field == field_value)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(
        session: AsyncSession,
        model: Type[T],
        limit: int = _HARD_LIMIT,
        offset: int = 0,
    ) -> List[T]:
        safe_limit = min(limit, _HARD_LIMIT)
        stmt = select(model).limit(safe_limit).offset(offset)
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        if len(rows) >= _HARD_LIMIT:
            logger.warning(
                f"AsyncDB.get_all({model.__name__}) 命中硬上限 {_HARD_LIMIT}，"
                f"可能存在未分页的全量查询"
            )
        return rows

    @staticmethod
    async def filter_by(
        session: AsyncSession,
        model: Type[T],
        limit: int = _HARD_LIMIT,
        offset: int = 0,
        **filters,
    ) -> List[T]:
        safe_limit = min(limit, _HARD_LIMIT)
        stmt = select(model)
        for field_name, field_value in filters.items():
            field = getattr(model, field_name)
            stmt = stmt.where(field == field_value)
        stmt = stmt.limit(safe_limit).offset(offset)
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        if len(rows) >= _HARD_LIMIT:
            logger.warning(
                f"AsyncDB.filter_by({model.__name__}, {filters}) 命中硬上限 {_HARD_LIMIT}"
            )
        return rows

    @staticmethod
    async def count(session: AsyncSession, model: Type[T], **filters) -> int:
        """计算满足条件的记录总数。"""
        stmt = select(func.count()).select_from(model)
        for field_name, field_value in filters.items():
            field = getattr(model, field_name)
            stmt = stmt.where(field == field_value)
        result = await session.scalar(stmt)
        return result or 0

    @staticmethod
    async def paginate(
        session: AsyncSession,
        model: Type[T],
        page: int = 1,
        page_size: int = 20,
        order_by=None,
        filters=None,
        include_total: bool = True,
    ) -> dict:
        """
        Offset 分页（适合浅翻页场景）。

        Returns:
            {"items": [...], "total": N, "page": P, "page_size": S, "has_more": bool}
        """
        safe_page_size = min(page_size, 100)
        offset = (max(1, page) - 1) * safe_page_size

        stmt = select(model)
        count_stmt = select(func.count()).select_from(model)

        if filters:
            for f in filters:
                stmt = stmt.where(f)
                count_stmt = count_stmt.where(f)

        if order_by is not None:
            stmt = stmt.order_by(order_by)

        stmt = stmt.limit(safe_page_size).offset(offset)
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        total = None
        if include_total:
            total = await session.scalar(count_stmt)

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": safe_page_size,
            "has_more": len(items) == safe_page_size,
        }

    @staticmethod
    async def create(session: AsyncSession, instance: T) -> T:
        try:
            session.add(instance)
            await session.flush()
            await session.refresh(instance)
            return instance
        except Exception as e:
            logger.error(f"创建失败: {e}")
            await session.rollback()
            raise

    @staticmethod
    async def update(session: AsyncSession, instance: T) -> T:
        try:
            await session.flush()
            await session.refresh(instance)
            return instance
        except Exception as e:
            logger.error(f"更新失败: {e}")
            await session.rollback()
            raise

    @staticmethod
    async def delete(session: AsyncSession, instance: T) -> bool:
        try:
            await session.delete(instance)
            await session.flush()
            return True
        except Exception as e:
            logger.error(f"删除失败: {e}")
            await session.rollback()
            return False

    @staticmethod
    async def commit(session: AsyncSession):
        try:
            await session.commit()
        except Exception as e:
            logger.error(f"提交失败: {e}")
            await session.rollback()
            raise

    @staticmethod
    async def rollback(session: AsyncSession):
        await session.rollback()
