"""
异步数据库工具
提供异步数据库查询的辅助函数
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Type, TypeVar, Optional, List
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class AsyncDB:
    """异步数据库操作工具类"""
    
    @staticmethod
    async def get_by_id(session: AsyncSession, model: Type[T], id: int) -> Optional[T]:
        """
        根据 ID 获取单个记录
        
        Args:
            session: 异步会话
            model: 模型类
            id: 记录 ID
        
        Returns:
            模型实例或 None
        """
        try:
            result = await session.get(model, id)
            return result
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return None
    
    @staticmethod
    async def get_by_field(
        session: AsyncSession,
        model: Type[T],
        field_name: str,
        field_value: any
    ) -> Optional[T]:
        """
        根据字段值获取单个记录
        
        Args:
            session: 异步会话
            model: 模型类
            field_name: 字段名
            field_value: 字段值
        
        Returns:
            模型实例或 None
        """
        try:
            field = getattr(model, field_name)
            stmt = select(model).where(field == field_value)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return None
    
    @staticmethod
    async def get_all(session: AsyncSession, model: Type[T]) -> List[T]:
        """
        获取所有记录
        
        Args:
            session: 异步会话
            model: 模型类
        
        Returns:
            记录列表
        """
        try:
            stmt = select(model)
            result = await session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return []
    
    @staticmethod
    async def filter_by(
        session: AsyncSession,
        model: Type[T],
        **filters
    ) -> List[T]:
        """
        根据条件过滤记录
        
        Args:
            session: 异步会话
            model: 模型类
            **filters: 过滤条件
        
        Returns:
            记录列表
        """
        try:
            stmt = select(model)
            for field_name, field_value in filters.items():
                field = getattr(model, field_name)
                stmt = stmt.where(field == field_value)
            result = await session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return []
    
    @staticmethod
    async def create(session: AsyncSession, instance: T) -> T:
        """
        创建新记录
        
        Args:
            session: 异步会话
            instance: 模型实例
        
        Returns:
            创建的模型实例
        """
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
        """
        更新记录
        
        Args:
            session: 异步会话
            instance: 模型实例
        
        Returns:
            更新的模型实例
        """
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
        """
        删除记录
        
        Args:
            session: 异步会话
            instance: 模型实例
        
        Returns:
            是否删除成功
        """
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
        """提交事务"""
        try:
            await session.commit()
        except Exception as e:
            logger.error(f"提交失败: {e}")
            await session.rollback()
            raise
    
    @staticmethod
    async def rollback(session: AsyncSession):
        """回滚事务"""
        await session.rollback()

