"""
异步向量数据库 Mapper
"""
from typing import Optional
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.vector_db import VectorDb
from app.utils.async_db import AsyncDB
import logging

logger = logging.getLogger(__name__)


class AsyncVectorMapper:
    """异步向量数据库数据访问层"""

    @staticmethod
    async def create_vector_db(
        session: AsyncSession,
        user_id: int,
        name: str,
        embedding_id: int,
        describe: Optional[str] = None,
        document_similarity: float = 0.7,
        organization_id: Optional[int] = None,
        **kwargs
    ) -> VectorDb:
        """创建向量数据库"""
        try:
            vector_db = VectorDb(
                user_id=user_id,
                name=name,
                embedding_id=embedding_id,
                describe=describe,
                document_similarity=document_similarity,
                organization_id=organization_id,
            )
            vector_db = await AsyncDB.create(session, vector_db)
            await AsyncDB.commit(session)
            return vector_db
        except Exception as e:
            await AsyncDB.rollback(session)
            raise Exception(f"创建向量数据库失败: {str(e)}")

    @staticmethod
    async def get_vector_db(session: AsyncSession, vector_db_id: int) -> Optional[VectorDb]:
        """获取向量数据库"""
        result = await session.execute(
            select(VectorDb).options(selectinload(VectorDb.user), selectinload(VectorDb.organization)).where(VectorDb.id == vector_db_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_document_by_id(session: AsyncSession, document_id: int):
        """根据ID获取文档"""
        from app.models.document import Document
        return await AsyncDB.get_by_id(session, Document, document_id)

    @staticmethod
    async def update_vector_db(
        session: AsyncSession,
        vector_db_id: int,
        name: Optional[str] = None,
        embedding_id: Optional[int] = None,
        describe: Optional[str] = None,
        document_similarity: Optional[float] = None,
        organization_id: Optional[int] = None,
        **kwargs
    ) -> Optional[VectorDb]:
        """更新向量数据库"""
        try:
            vector_db = await AsyncVectorMapper.get_vector_db(session, vector_db_id)
            if not vector_db:
                return None

            if name is not None:
                vector_db.name = name
            if embedding_id is not None:
                vector_db.embedding_id = embedding_id
            if describe is not None:
                vector_db.describe = describe
            if document_similarity is not None:
                vector_db.document_similarity = document_similarity
            if organization_id is not None:
                vector_db.organization_id = organization_id

            vector_db = await AsyncDB.update(session, vector_db)
            await AsyncDB.commit(session)
            return vector_db
        except Exception as e:
            await AsyncDB.rollback(session)
            raise Exception(f"更新向量数据库失败: {str(e)}")

    @staticmethod
    async def delete_vector_db(session: AsyncSession, vector_db_id: int) -> bool:
        """删除向量数据库"""
        try:
            vector_db = await AsyncVectorMapper.get_vector_db(session, vector_db_id)
            if not vector_db:
                return False

            await AsyncDB.delete(session, vector_db)
            await AsyncDB.commit(session)
            return True
        except Exception as e:
            await AsyncDB.rollback(session)
            raise Exception(f"删除向量数据库失败: {str(e)}")

    @staticmethod
    async def get_user_vector_dbs(session: AsyncSession, user_id: int) -> list[VectorDb]:
        """获取用户的向量数据库列表"""
        return await AsyncDB.filter_by(session, VectorDb, user_id=user_id)

    @staticmethod
    async def get_vector_dbs_by_org_ids(
        session: AsyncSession,
        org_ids: list[int]
    ) -> list[VectorDb]:
        """根据组织 ID 列表获取向量数据库"""
        if not org_ids:
            return []
        stmt = select(VectorDb).options(
            selectinload(VectorDb.user), selectinload(VectorDb.organization)
        ).where(VectorDb.organization_id.in_(org_ids))
        result = await session.execute(stmt)
        return list(result.scalars().all())
