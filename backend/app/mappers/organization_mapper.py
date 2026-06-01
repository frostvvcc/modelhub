"""
异步组织架构 Mapper
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.utils.async_db import AsyncDB
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


class AsyncOrganizationMapper:
    """异步组织架构数据访问层"""
    
    @staticmethod
    async def get_organization_by_id(
        session: AsyncSession, 
        organization_id: int
    ) -> Optional[Organization]:
        """根据 ID 获取组织"""
        return await AsyncDB.get_by_id(session, Organization, organization_id)
    
    @staticmethod
    async def get_organization_by_code(
        session: AsyncSession, 
        code: str
    ) -> Optional[Organization]:
        """根据编码获取组织"""
        return await AsyncDB.get_by_field(session, Organization, "code", code)
    
    @staticmethod
    async def create_organization(
        session: AsyncSession,
        name: str,
        code: str,
        org_type: str,
        parent_id: Optional[int] = None,
        school_id: Optional[int] = None,
        level: int = 1,
        path: Optional[str] = None,
        description: Optional[str] = None,
        status: str = "active"
    ) -> Organization:
        """创建组织"""
        # 检查编码是否已存在
        existing = await AsyncOrganizationMapper.get_organization_by_code(session, code)
        if existing:
            raise ValueError(f"Organization code '{code}' already exists")
        
        organization = Organization(
            name=name,
            code=code,
            type=org_type,
            parent_id=parent_id,
            school_id=school_id,
            level=level,
            path=path,
            description=description,
            status=status
        )
        organization = await AsyncDB.create(session, organization)
        await AsyncDB.commit(session)
        return organization
    
    @staticmethod
    async def update_organization(
        session: AsyncSession,
        organization_id: int,
        **kwargs
    ) -> Optional[Organization]:
        """更新组织信息"""
        organization = await AsyncOrganizationMapper.get_organization_by_id(session, organization_id)
        if not organization:
            return None
        
        for key, value in kwargs.items():
            if hasattr(organization, key):
                setattr(organization, key, value)
        
        await AsyncDB.commit(session)
        return organization
    
    @staticmethod
    async def delete_organization(
        session: AsyncSession,
        organization_id: int
    ) -> bool:
        """删除组织（需要先删除子组织）"""
        organization = await AsyncOrganizationMapper.get_organization_by_id(session, organization_id)
        if not organization:
            return False
        
        # 检查是否有子组织
        children = await AsyncOrganizationMapper.get_children(session, organization_id)
        if children:
            raise ValueError("Cannot delete organization with children")
        
        await AsyncDB.delete(session, organization)
        await AsyncDB.commit(session)
        return True
    
    @staticmethod
    async def get_children(
        session: AsyncSession,
        parent_id: int
    ) -> List[Organization]:
        """获取子组织列表"""
        stmt = select(Organization).where(Organization.parent_id == parent_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_tree(
        session: AsyncSession,
        root_id: int,
        include_inactive: bool = False
    ) -> Optional[Organization]:
        """获取组织树（递归加载子节点）"""
        # 先获取根节点
        stmt = select(Organization).where(Organization.id == root_id)
        if not include_inactive:
            stmt = stmt.where(Organization.status == "active")
        
        result = await session.execute(stmt)
        root = result.scalar_one_or_none()
        
        if not root:
            return None
        
        # 获取所有子节点（一次性查询，避免递归查询关系）
        all_orgs = await AsyncOrganizationMapper._get_all_descendants(
            session, root_id, include_inactive
        )
        
        # 构建父子关系映射
        org_dict = {org.id: org for org in all_orgs}
        org_dict[root.id] = root
        
        # 为每个节点设置 _children 属性（临时属性，不访问关系）
        for org in all_orgs:
            if not hasattr(org, '_children'):
                org._children = []
            if org.parent_id and org.parent_id in org_dict:
                parent = org_dict[org.parent_id]
                if not hasattr(parent, '_children'):
                    parent._children = []
                parent._children.append(org)
        
        return root
    
    @staticmethod
    async def _get_all_descendants(
        session: AsyncSession,
        root_id: int,
        include_inactive: bool = False
    ) -> List[Organization]:
        """获取所有后代节点（使用路径查询）"""
        # 先获取根节点路径
        root = await AsyncOrganizationMapper.get_organization_by_id(session, root_id)
        if not root:
            return []
        
        # 使用路径前缀查询所有子节点
        if root.path:
            path_prefix = f"{root.path}/"
        else:
            path_prefix = f"{root_id}/"
        
        stmt = select(Organization).where(
            Organization.path.like(f"{path_prefix}%")
        )
        if not include_inactive:
            stmt = stmt.where(Organization.status == "active")
        
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_path(
        session: AsyncSession,
        organization_id: int
    ) -> List[Organization]:
        """获取组织路径（向上查找）"""
        path = []
        current_id = organization_id
        
        while current_id:
            org = await AsyncOrganizationMapper.get_organization_by_id(session, current_id)
            if not org:
                break
            path.insert(0, org)
            current_id = org.parent_id
        
        return path
    
    @staticmethod
    async def get_by_school(
        session: AsyncSession,
        school_id: int,
        include_inactive: bool = False
    ) -> List[Organization]:
        """获取学校下的所有组织"""
        stmt = select(Organization).where(Organization.school_id == school_id)
        if not include_inactive:
            stmt = stmt.where(Organization.status == "active")
        stmt = stmt.order_by(Organization.level, Organization.name)
        
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_by_path_prefix(
        session: AsyncSession,
        path_prefix: str
    ) -> List[Organization]:
        """根据路径前缀查询组织（用于快速查询子树）"""
        stmt = select(Organization).where(
            Organization.path.like(f"{path_prefix}%")
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    # 组织成员相关方法
    @staticmethod
    async def add_member(
        session: AsyncSession,
        user_id: int,
        organization_id: int,
        role: str = "member"
    ) -> OrganizationMember:
        """添加组织成员"""
        # 检查是否已存在
        stmt = select(OrganizationMember).where(
            and_(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == organization_id
            )
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            # 更新现有成员
            existing.role = role
            existing.status = "active"
            await AsyncDB.commit(session)
            return existing
        
        member = OrganizationMember(
            user_id=user_id,
            organization_id=organization_id,
            role=role,
            status="active"
        )
        member = await AsyncDB.create(session, member)
        await AsyncDB.commit(session)
        return member
    
    @staticmethod
    async def remove_member(
        session: AsyncSession,
        user_id: int,
        organization_id: int
    ) -> bool:
        """移除组织成员"""
        stmt = select(OrganizationMember).where(
            and_(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == organization_id
            )
        )
        result = await session.execute(stmt)
        member = result.scalar_one_or_none()
        
        if not member:
            return False
        
        await AsyncDB.delete(session, member)
        await AsyncDB.commit(session)
        return True
    
    @staticmethod
    async def get_members(
        session: AsyncSession,
        organization_id: int,
        include_inactive: bool = False
    ) -> List[OrganizationMember]:
        """获取组织成员列表"""
        stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id
        )
        if not include_inactive:
            stmt = stmt.where(OrganizationMember.status == "active")
        
        stmt = stmt.options(selectinload(OrganizationMember.user))
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_user_organizations(
        session: AsyncSession,
        user_id: int,
        include_inactive: bool = False
    ) -> List[Organization]:
        """获取用户所属的所有组织"""
        stmt = select(Organization).join(
            OrganizationMember,
            Organization.id == OrganizationMember.organization_id
        ).where(OrganizationMember.user_id == user_id)
        
        if not include_inactive:
            stmt = stmt.where(
                and_(
                    Organization.status == "active",
                    OrganizationMember.status == "active"
                )
            )
        
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def check_user_in_organization(
        session: AsyncSession,
        user_id: int,
        organization_id: int
    ) -> bool:
        """检查用户是否在组织中"""
        stmt = select(OrganizationMember).where(
            and_(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.status == "active"
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

