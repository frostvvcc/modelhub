"""
异步组织架构 Service
处理组织架构相关的业务逻辑
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional, Dict, Any
from app.mappers.organization_mapper import AsyncOrganizationMapper
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.utils.logger_config import get_logger
from app.utils.cache import cache_result, clear_cache
from app.utils.error_handler import (
    NotFoundError,
    ValidationError,
    InternalServerError
)

logger = get_logger(__name__)


class AsyncOrganizationService:
    """异步组织架构服务类"""
    
    @staticmethod
    async def create_organization(
        session: AsyncSession,
        name: str,
        code: str,
        org_type: str,
        parent_id: Optional[int] = None,
        description: Optional[str] = None,
        school_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        创建组织节点
        
        Args:
            session: 数据库会话
            name: 组织名称
            code: 组织编码
            org_type: 组织类型
            parent_id: 父组织ID
            description: 描述
            school_id: 学校ID（如果创建的是学校，则为None）
        
        Returns:
            创建的组织信息
        """
        logger.info(f"创建组织: name={name}, code={code}, type={org_type}, parent_id={parent_id}")
        
        try:
            # 确定层级和路径
            level = 1
            path = None
            final_school_id = school_id
            
            if parent_id:
                # 获取父组织信息
                parent = await AsyncOrganizationMapper.get_organization_by_id(session, parent_id)
                if not parent:
                    raise ValidationError("父组织不存在")
                
                level = parent.level + 1
                path = f"{parent.path}/{parent.id}" if parent.path else str(parent.id)
                final_school_id = parent.school_id or parent.id  # 如果父组织是学校，则使用父组织ID
            
            elif org_type == "school":
                # 创建学校（根节点）
                level = 1
                path = None
                final_school_id = None
            else:
                raise ValidationError("非学校组织必须指定父组织")
            
            # 创建组织
            organization = await AsyncOrganizationMapper.create_organization(
                session=session,
                name=name,
                code=code,
                org_type=org_type,
                parent_id=parent_id,
                school_id=final_school_id,
                level=level,
                path=path,
                description=description,
                status="active"
            )
            
            # 更新路径（包含自己的ID）
            if organization.id:
                new_path = f"{path}/{organization.id}" if path else str(organization.id)
                await AsyncOrganizationMapper.update_organization(
                    session, organization.id, path=new_path
                )
                organization.path = new_path
            
            logger.info(f"成功创建组织: id={organization.id}")
            # 清除组织树缓存
            clear_cache("org_tree:*")
            await session.refresh(organization)
            return organization.to_dict()
            
        except ValueError as e:
            logger.warning(f"创建组织失败: {str(e)}")
            raise ValidationError(str(e))
        except Exception as e:
            logger.error(f"创建组织失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"创建组织失败: {str(e)}")
    
    @staticmethod
    async def get_organization(
        session: AsyncSession,
        organization_id: int,
        include_children: bool = False,
        include_members: bool = False
    ) -> Dict[str, Any]:
        """获取组织详情"""
        logger.debug(f"获取组织详情: id={organization_id}")
        
        organization = await AsyncOrganizationMapper.get_organization_by_id(session, organization_id)
        if not organization:
            raise NotFoundError("组织不存在")
        
        # 异步加载子节点和成员，避免访问 lazy 关系
        children_list = None
        members_list = None
        
        if include_children:
            children = await AsyncOrganizationMapper.get_children(session, organization_id)
            children_list = children
        
        if include_members:
            members = await AsyncOrganizationMapper.get_members(session, organization_id)
            members_list = members
        
        return organization.to_dict(
            include_children=include_children,
            include_members=include_members,
            children_list=children_list,
            members_list=members_list
        )
    
    @staticmethod
    async def update_organization(
        session: AsyncSession,
        organization_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """更新组织信息"""
        logger.info(f"更新组织: id={organization_id}")
        
        update_data = {}
        if name is not None:
            update_data['name'] = name
        if description is not None:
            update_data['description'] = description
        if status is not None:
            if status not in ['active', 'inactive', 'suspended']:
                raise ValidationError("无效的状态值")
            update_data['status'] = status
        
        organization = await AsyncOrganizationMapper.update_organization(
            session, organization_id, **update_data
        )
        
        if not organization:
            raise NotFoundError("组织不存在")
        
        logger.info(f"成功更新组织: id={organization_id}")
        # 清除组织树缓存
        clear_cache("org_tree:*")
        await session.refresh(organization)
        return organization.to_dict()
    
    @staticmethod
    async def delete_organization(
        session: AsyncSession,
        organization_id: int
    ) -> bool:
        """删除组织（需要先删除子组织）"""
        logger.info(f"删除组织: id={organization_id}")
        
        try:
            result = await AsyncOrganizationMapper.delete_organization(session, organization_id)
            if result:
                logger.info(f"成功删除组织: id={organization_id}")
                # 清除组织树缓存
                clear_cache("org_tree:*")
            return result
        except ValueError as e:
            logger.warning(f"删除组织失败: {str(e)}")
            raise ValidationError(str(e))
        except Exception as e:
            logger.error(f"删除组织失败: {str(e)}", exc_info=True)
            raise InternalServerError(f"删除组织失败: {str(e)}")
    
    @staticmethod
    async def get_children(
        session: AsyncSession,
        parent_id: int
    ) -> List[Dict[str, Any]]:
        """获取子组织列表"""
        logger.debug(f"获取子组织列表: parent_id={parent_id}")
        
        children = await AsyncOrganizationMapper.get_children(session, parent_id)
        return [child.to_dict() for child in children]
    
    @staticmethod
    async def get_tree(
        session: AsyncSession,
        root_id: int,
        include_inactive: bool = False
    ) -> Dict[str, Any]:
        """获取组织树"""
        logger.debug(f"获取组织树: root_id={root_id}")
        
        root = await AsyncOrganizationMapper.get_tree(session, root_id, include_inactive)
        if not root:
            raise NotFoundError("组织不存在")
        
        def build_tree(org: Organization) -> Dict[str, Any]:
            """递归构建树结构"""
            result = org.to_dict()
            # 使用临时属性 _children，避免访问 lazy 关系
            children = getattr(org, '_children', [])
            if children:
                result['children'] = [build_tree(child) for child in children]
            else:
                result['children'] = []
            return result
        
        return build_tree(root)
    
    @staticmethod
    async def get_path(
        session: AsyncSession,
        organization_id: int
    ) -> List[Dict[str, Any]]:
        """获取组织路径（向上查找）"""
        logger.debug(f"获取组织路径: id={organization_id}")
        
        path = await AsyncOrganizationMapper.get_path(session, organization_id)
        return [org.to_dict() for org in path]
    
    @staticmethod
    async def add_member(
        session: AsyncSession,
        user_id: int,
        organization_id: int,
        role: str = "member"
    ) -> Dict[str, Any]:
        """添加组织成员"""
        logger.info(f"添加组织成员: user_id={user_id}, organization_id={organization_id}, role={role}")
        
        # 验证组织是否存在
        organization = await AsyncOrganizationMapper.get_organization_by_id(session, organization_id)
        if not organization:
            raise NotFoundError("组织不存在")
        
        # 验证角色
        valid_roles = ['admin', 'teacher', 'student', 'guest', 'member']
        if role not in valid_roles:
            raise ValidationError(f"无效的角色: {role}")
        
        member = await AsyncOrganizationMapper.add_member(
            session, user_id, organization_id, role
        )
        
        logger.info(f"成功添加组织成员: id={member.id}")
        return member.to_dict()
    
    @staticmethod
    async def remove_member(
        session: AsyncSession,
        user_id: int,
        organization_id: int
    ) -> bool:
        """移除组织成员"""
        logger.info(f"移除组织成员: user_id={user_id}, organization_id={organization_id}")
        
        result = await AsyncOrganizationMapper.remove_member(session, user_id, organization_id)
        if result:
            logger.info(f"成功移除组织成员")
        return result
    
    @staticmethod
    async def get_members(
        session: AsyncSession,
        organization_id: int,
        include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        """获取组织成员列表"""
        logger.debug(f"获取组织成员列表: organization_id={organization_id}")
        
        members = await AsyncOrganizationMapper.get_members(
            session, organization_id, include_inactive
        )
        return [member.to_dict() for member in members]
    
    @staticmethod
    async def get_user_organizations(
        session: AsyncSession,
        user_id: int
    ) -> List[Dict[str, Any]]:
        """获取用户所属的所有组织"""
        logger.debug(f"获取用户组织: user_id={user_id}")
        
        organizations = await AsyncOrganizationMapper.get_user_organizations(session, user_id)
        return [org.to_dict() for org in organizations]
    
    @staticmethod
    async def check_user_in_organization(
        session: AsyncSession,
        user_id: int,
        organization_id: int
    ) -> bool:
        """检查用户是否在组织中"""
        return await AsyncOrganizationMapper.check_user_in_organization(
            session, user_id, organization_id
        )

    @staticmethod
    async def get_schools(session: AsyncSession) -> list:
        """获取所有学校列表（公开接口）"""
        from app.models.organization import Organization
        from sqlalchemy import select
        stmt = select(Organization).where(
            Organization.type == "school",
            Organization.status == "active"
        ).order_by(Organization.name)
        result = await session.execute(stmt)
        schools = result.scalars().all()
        return [
            {"id": s.id, "name": s.name, "code": s.code}
            for s in schools
        ]

    @staticmethod
    async def get_departments_for_register(session: AsyncSession, school_id: int) -> list:
        """获取学校下的学院/部门列表（公开接口，注册用）"""
        from app.models.organization import Organization
        from sqlalchemy import select
        stmt = select(Organization).where(
            Organization.parent_id == school_id,
            Organization.status == "active"
        ).order_by(Organization.name)
        result = await session.execute(stmt)
        orgs = result.scalars().all()
        return [
            {"id": o.id, "name": o.name, "code": o.code, "type": o.type}
            for o in orgs
        ]

    @staticmethod
    async def get_majors_for_register(session: AsyncSession, college_id: int) -> list:
        """获取学院下的专业列表（公开接口，注册用）"""
        from app.models.organization import Organization
        from sqlalchemy import select as sel
        stmt = sel(Organization).where(
            Organization.parent_id == college_id,
            Organization.type == "major",
            Organization.status == "active"
        ).order_by(Organization.name)
        result = await session.execute(stmt)
        orgs = result.scalars().all()
        return [
            {"id": o.id, "name": o.name, "code": o.code, "type": o.type}
            for o in orgs
        ]

    @staticmethod
    async def get_major_grade_distribution(
        session: AsyncSession,
        major_id: int
    ) -> List[Dict[str, Any]]:
        """获取某专业下各入学年份的学生人数分布，始终返回近4个年级（含0人的年级）"""
        stmt = (
            select(User.enrollment_year, func.count(User.id))
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(
                OrganizationMember.organization_id == major_id,
                OrganizationMember.status == "active",
                User.role == "student",
                User.status == "active",
                User.enrollment_year.isnot(None)
            )
            .group_by(User.enrollment_year)
            .order_by(User.enrollment_year.desc())
        )
        result = await session.execute(stmt)
        rows = result.all()
        count_map = {year: count for year, count in rows}

        from datetime import date
        current_year = date.today().year
        all_years = range(current_year - 4, current_year)
        return [
            {"enrollment_year": y, "student_count": count_map.get(y, 0)}
            for y in sorted(all_years, reverse=True)
        ]

