"""
教学空间 Service
"""
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, delete, func
from sqlalchemy.orm import selectinload, joinedload
from typing import List, Optional

from app.models.teaching_space import TeachingSpace, TeachingSpaceMajor, TeachingSpaceResource, TeachingSpaceStudent
from app.models.organization import Organization, OrganizationMember
from app.models.vector_db import VectorDb
from app.models.bot import Bot
from app.models.user import User
from app.utils.logger_config import get_logger
from app.utils.error_handler import NotFoundError, ValidationError, ForbiddenError

logger = get_logger(__name__)


class AsyncTeachingSpaceService:

    @staticmethod
    async def _count_valid_resources(session: AsyncSession, space_id: int) -> int:
        """统计教学空间中仍然存在的资源数量（排除已删除资源的孤儿记录）"""
        stmt = select(TeachingSpaceResource).where(TeachingSpaceResource.space_id == space_id)
        result = await session.execute(stmt)
        resources = result.scalars().all()
        if not resources:
            return 0

        vdb_ids = [r.resource_id for r in resources if r.resource_type == "vector_db"]
        bot_ids = [r.resource_id for r in resources if r.resource_type == "bot"]
        count = 0

        if vdb_ids:
            vdb_stmt = select(func.count()).select_from(VectorDb).where(VectorDb.id.in_(vdb_ids))
            vdb_res = await session.execute(vdb_stmt)
            count += vdb_res.scalar() or 0

        if bot_ids:
            bot_stmt = select(func.count()).select_from(Bot).where(Bot.id.in_(bot_ids))
            bot_res = await session.execute(bot_stmt)
            count += bot_res.scalar() or 0

        return count

    @staticmethod
    async def _count_space_members(session: AsyncSession, space_id: int) -> int:
        """统计教学空间学生人数（年级感知）"""
        bindings_stmt = (
            select(TeachingSpaceMajor.major_id, TeachingSpaceMajor.enrollment_year)
            .where(TeachingSpaceMajor.space_id == space_id)
        )
        bindings_res = await session.execute(bindings_stmt)
        bindings = bindings_res.all()
        if not bindings:
            return 0

        conditions = []
        for major_id, ey in bindings:
            if ey is None:
                conditions.append(OrganizationMember.organization_id == major_id)
            else:
                conditions.append(
                    and_(OrganizationMember.organization_id == major_id, User.enrollment_year == ey)
                )

        member_stmt = (
            select(func.count(func.distinct(OrganizationMember.user_id)))
            .join(User, User.id == OrganizationMember.user_id)
            .where(
                or_(*conditions),
                OrganizationMember.status == "active",
                User.role == "student",
                User.status == "active"
            )
        )
        member_res = await session.execute(member_stmt)
        return member_res.scalar() or 0

    @staticmethod
    async def _generate_space_code(session: AsyncSession, teacher_id: int) -> str:
        """生成结构化编号: {学院code}-{年���2位}-{序号3位}"""
        college_stmt = (
            select(Organization)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(
                OrganizationMember.user_id == teacher_id,
                OrganizationMember.status == "active",
                Organization.type == "college"
            )
        )
        college_res = await session.execute(college_stmt)
        college = college_res.scalars().first()
        college_code = college.code if college else "XX"

        year_suffix = datetime.now().strftime("%y")
        prefix = f"{college_code}-{year_suffix}-"

        max_stmt = (
            select(func.max(TeachingSpace.space_code))
            .where(TeachingSpace.space_code.like(f"{prefix}%"))
        )
        max_res = await session.execute(max_stmt)
        max_code = max_res.scalar()

        if max_code:
            seq = int(max_code.split("-")[-1]) + 1
        else:
            seq = 1

        return f"{prefix}{seq:03d}"

    @staticmethod
    async def create_space(session: AsyncSession, teacher: User, name: str, description: Optional[str] = None) -> dict:
        if not name or not name.strip():
            raise ValidationError("空间名称不能为空")

        space_code = await AsyncTeachingSpaceService._generate_space_code(session, teacher.id)

        space = TeachingSpace(
            name=name.strip(),
            description=description,
            teacher_id=teacher.id,
            school_id=teacher.school_id,
            space_code=space_code,
        )
        session.add(space)
        await session.commit()
        stmt = (
            select(TeachingSpace)
            .options(selectinload(TeachingSpace.teacher))
            .where(TeachingSpace.id == space.id)
        )
        result = await session.execute(stmt)
        space = result.scalar_one()
        return space.to_dict()

    @staticmethod
    async def list_spaces_for_teacher(session: AsyncSession, teacher_id: int) -> List[dict]:
        stmt = (
            select(TeachingSpace)
            .options(joinedload(TeachingSpace.teacher))
            .where(TeachingSpace.teacher_id == teacher_id, TeachingSpace.status == "active")
            .order_by(TeachingSpace.updated_at.desc())
        )
        result = await session.execute(stmt)
        spaces = result.scalars().unique().all()
        space_dicts = []
        for space in spaces:
            d = space.to_dict()
            count_stmt = select(func.count()).select_from(TeachingSpaceMajor).where(TeachingSpaceMajor.space_id == space.id)
            count_res = await session.execute(count_stmt)
            d['major_count'] = count_res.scalar() or 0
            d['resource_count'] = await AsyncTeachingSpaceService._count_valid_resources(session, space.id)
            d['member_count'] = await AsyncTeachingSpaceService._count_space_members(session, space.id)
            space_dicts.append(d)
        return space_dicts

    @staticmethod
    async def list_spaces_for_student(session: AsyncSession, student_id: int) -> List[dict]:
        """获取学生所在专业被绑定的所有教学空间 + 直接添加的空间（年级感知）"""
        seen_ids = set()
        all_spaces = []

        student_stmt = select(User).where(User.id == student_id)
        student_res = await session.execute(student_stmt)
        student = student_res.scalars().first()
        student_enrollment_year = student.enrollment_year if student else None

        student_major_stmt = (
            select(OrganizationMember.organization_id)
            .join(Organization, Organization.id == OrganizationMember.organization_id)
            .where(
                OrganizationMember.user_id == student_id,
                OrganizationMember.status == "active",
                Organization.type == "major"
            )
        )
        student_major_res = await session.execute(student_major_stmt)
        major_ids = [row[0] for row in student_major_res.all()]

        if major_ids:
            year_conditions = [
                and_(
                    TeachingSpaceMajor.major_id.in_(major_ids),
                    TeachingSpaceMajor.enrollment_year.is_(None)
                )
            ]
            if student_enrollment_year:
                year_conditions.append(
                    and_(
                        TeachingSpaceMajor.major_id.in_(major_ids),
                        TeachingSpaceMajor.enrollment_year == student_enrollment_year
                    )
                )

            stmt = (
                select(TeachingSpace)
                .join(TeachingSpaceMajor, TeachingSpaceMajor.space_id == TeachingSpace.id)
                .options(joinedload(TeachingSpace.teacher))
                .where(
                    or_(*year_conditions),
                    TeachingSpace.status == "active"
                )
                .distinct()
                .order_by(TeachingSpace.updated_at.desc())
            )
            result = await session.execute(stmt)
            for s in result.scalars().unique().all():
                seen_ids.add(s.id)
                all_spaces.append(s.to_dict())

        try:
            direct_stmt = (
                select(TeachingSpace)
                .join(TeachingSpaceStudent, TeachingSpaceStudent.space_id == TeachingSpace.id)
                .options(joinedload(TeachingSpace.teacher))
                .where(
                    TeachingSpaceStudent.student_id == student_id,
                    TeachingSpace.status == "active"
                )
                .order_by(TeachingSpace.updated_at.desc())
            )
            direct_res = await session.execute(direct_stmt)
            for s in direct_res.scalars().unique().all():
                if s.id not in seen_ids:
                    all_spaces.append(s.to_dict())
        except Exception as e:
            logger.warning(f"查询直接添加的空间失败: {e}")

        return all_spaces

    @staticmethod
    async def list_all_spaces(session: AsyncSession, school_id: Optional[int] = None, organization_id: Optional[int] = None) -> List[dict]:
        """管理员获取所有教学空间，可按学院筛选"""
        stmt = (
            select(TeachingSpace)
            .options(joinedload(TeachingSpace.teacher))
            .where(TeachingSpace.status == "active")
            .order_by(TeachingSpace.updated_at.desc())
        )
        if school_id:
            stmt = stmt.where(TeachingSpace.school_id == school_id)

        result = await session.execute(stmt)
        spaces = result.scalars().unique().all()

        if organization_id:
            teacher_ids_stmt = (
                select(OrganizationMember.user_id)
                .where(
                    OrganizationMember.organization_id == organization_id,
                    OrganizationMember.status == "active"
                )
            )
            teacher_ids_res = await session.execute(teacher_ids_stmt)
            teacher_ids = set(row[0] for row in teacher_ids_res.all())
            spaces = [s for s in spaces if s.teacher_id in teacher_ids]

        space_dicts = []
        for space in spaces:
            d = space.to_dict()
            count_stmt = select(func.count()).select_from(TeachingSpaceMajor).where(TeachingSpaceMajor.space_id == space.id)
            count_res = await session.execute(count_stmt)
            d['major_count'] = count_res.scalar() or 0
            d['resource_count'] = await AsyncTeachingSpaceService._count_valid_resources(session, space.id)
            teacher_college_stmt = (
                select(Organization)
                .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
                .where(
                    OrganizationMember.user_id == space.teacher_id,
                    OrganizationMember.status == "active",
                    Organization.type == "college"
                )
            )
            college_res = await session.execute(teacher_college_stmt)
            college = college_res.scalars().first()
            d['teacher_college_id'] = college.id if college else None
            d['teacher_college_name'] = college.name if college else None
            d['member_count'] = await AsyncTeachingSpaceService._count_space_members(session, space.id)
            space_dicts.append(d)
        return space_dicts

    @staticmethod
    async def get_space(session: AsyncSession, space_id: int) -> dict:
        stmt = select(TeachingSpace).options(joinedload(TeachingSpace.teacher)).where(TeachingSpace.id == space_id)
        result = await session.execute(stmt)
        space = result.scalars().first()
        if not space:
            raise NotFoundError("教学空间不存在")
        d = space.to_dict()
        college_stmt = (
            select(Organization)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(
                OrganizationMember.user_id == space.teacher_id,
                OrganizationMember.status == "active",
                Organization.type == "college"
            )
        )
        college_res = await session.execute(college_stmt)
        college = college_res.scalars().first()
        d['teacher_college_id'] = college.id if college else None
        d['teacher_college_name'] = college.name if college else None
        return d

    @staticmethod
    async def update_space(session: AsyncSession, space_id: int, teacher_id: int, name: Optional[str] = None, description: Optional[str] = None, status: Optional[str] = None, user_role: str = "teacher") -> dict:
        stmt = select(TeachingSpace).options(joinedload(TeachingSpace.teacher)).where(TeachingSpace.id == space_id)
        result = await session.execute(stmt)
        space = result.scalars().first()
        if not space:
            raise NotFoundError("教学空间不存在")
        if user_role != "admin" and space.teacher_id != teacher_id:
            raise ForbiddenError("无权修改此教学空间")
        if name is not None:
            space.name = name.strip()
        if description is not None:
            space.description = description
        if status is not None:
            if status not in ("active", "archived"):
                raise ValidationError("状态只能是 active 或 archived")
            space.status = status
        await session.commit()
        # 重新查询加载 teacher 关系
        stmt2 = select(TeachingSpace).options(selectinload(TeachingSpace.teacher)).where(TeachingSpace.id == space_id)
        result2 = await session.execute(stmt2)
        space = result2.scalar_one()
        return space.to_dict()

    @staticmethod
    async def delete_space(session: AsyncSession, space_id: int, teacher_id: int, user_role: str = "teacher") -> bool:
        stmt = select(TeachingSpace).where(TeachingSpace.id == space_id)
        result = await session.execute(stmt)
        space = result.scalars().first()
        if not space:
            raise NotFoundError("教学空间不存在")
        if user_role != "admin" and space.teacher_id != teacher_id:
            raise ForbiddenError("无权删除此教学空间")
        await session.delete(space)
        await session.commit()
        return True

    @staticmethod
    async def bind_major(session: AsyncSession, space_id: int, major_id: int, teacher_id: int, user_role: str = "teacher", enrollment_year: Optional[int] = None) -> dict:
        space_stmt = select(TeachingSpace).where(TeachingSpace.id == space_id)
        space_res = await session.execute(space_stmt)
        space = space_res.scalars().first()
        if not space:
            raise NotFoundError("教学空间不存在")
        if user_role != "admin" and space.teacher_id != teacher_id:
            raise ForbiddenError("无权操作此教学空间")

        org_stmt = select(Organization).where(Organization.id == major_id, Organization.type == "major", Organization.status == "active")
        org_res = await session.execute(org_stmt)
        major = org_res.scalars().first()
        if not major:
            raise ValidationError("指定的专业不存在或不是专业类型")

        existing_stmt = select(TeachingSpaceMajor).where(
            TeachingSpaceMajor.space_id == space_id,
            TeachingSpaceMajor.major_id == major_id,
            TeachingSpaceMajor.enrollment_year == enrollment_year if enrollment_year else TeachingSpaceMajor.enrollment_year.is_(None)
        )
        existing_res = await session.execute(existing_stmt)
        if existing_res.scalars().first():
            year_label = f"{enrollment_year}级" if enrollment_year else "全部年级"
            raise ValidationError(f"该专业（{year_label}）已绑定到此空间")

        binding = TeachingSpaceMajor(space_id=space_id, major_id=major_id, enrollment_year=enrollment_year)
        session.add(binding)
        await session.commit()
        stmt2 = select(TeachingSpaceMajor).options(selectinload(TeachingSpaceMajor.major)).where(TeachingSpaceMajor.id == binding.id)
        result2 = await session.execute(stmt2)
        binding = result2.scalar_one()
        return binding.to_dict()

    @staticmethod
    async def unbind_major(session: AsyncSession, space_id: int, major_id: int, teacher_id: int, user_role: str = "teacher", enrollment_year: Optional[int] = None) -> bool:
        space_stmt = select(TeachingSpace).where(TeachingSpace.id == space_id)
        space_res = await session.execute(space_stmt)
        space = space_res.scalars().first()
        if not space:
            raise NotFoundError("教学空间不存在")
        if user_role != "admin" and space.teacher_id != teacher_id:
            raise ForbiddenError("无权操作此教学空间")

        conditions = [
            TeachingSpaceMajor.space_id == space_id,
            TeachingSpaceMajor.major_id == major_id,
        ]
        if enrollment_year is not None:
            conditions.append(TeachingSpaceMajor.enrollment_year == enrollment_year)
        else:
            conditions.append(TeachingSpaceMajor.enrollment_year.is_(None))

        stmt = delete(TeachingSpaceMajor).where(*conditions)
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount > 0

    @staticmethod
    async def get_bound_majors(session: AsyncSession, space_id: int) -> List[dict]:
        stmt = (
            select(TeachingSpaceMajor)
            .options(joinedload(TeachingSpaceMajor.major))
            .where(TeachingSpaceMajor.space_id == space_id)
        )
        result = await session.execute(stmt)
        bindings = result.scalars().unique().all()
        return [b.to_dict() for b in bindings]

    @staticmethod
    async def get_spaces_by_major(session: AsyncSession, major_id: int) -> List[dict]:
        stmt = (
            select(TeachingSpace)
            .join(TeachingSpaceMajor, TeachingSpaceMajor.space_id == TeachingSpace.id)
            .options(joinedload(TeachingSpace.teacher))
            .where(
                TeachingSpaceMajor.major_id == major_id,
                TeachingSpace.status == "active"
            )
            .order_by(TeachingSpace.updated_at.desc())
        )
        result = await session.execute(stmt)
        spaces = result.scalars().unique().all()

        space_dicts = []
        for space in spaces:
            d = space.to_dict()
            count_stmt = select(func.count()).select_from(TeachingSpaceMajor).where(TeachingSpaceMajor.space_id == space.id)
            count_res = await session.execute(count_stmt)
            d['major_count'] = count_res.scalar() or 0
            d['resource_count'] = await AsyncTeachingSpaceService._count_valid_resources(session, space.id)
            d['member_count'] = await AsyncTeachingSpaceService._count_space_members(session, space.id)
            space_dicts.append(d)
        return space_dicts

    @staticmethod
    async def get_space_students(session: AsyncSession, space_id: int) -> List[dict]:
        """获取空间内所有学生（通过绑定专业 + 直接添加），年级感知"""
        seen = set()
        students = []

        bindings_stmt = (
            select(TeachingSpaceMajor.major_id, TeachingSpaceMajor.enrollment_year)
            .where(TeachingSpaceMajor.space_id == space_id)
        )
        bindings_res = await session.execute(bindings_stmt)
        bindings = bindings_res.all()
        major_ids = list(set(row[0] for row in bindings))

        if major_ids:
            major_name_stmt = select(Organization.id, Organization.name).where(Organization.id.in_(major_ids))
            major_name_res = await session.execute(major_name_stmt)
            major_name_map = {row[0]: row[1] for row in major_name_res.all()}

            year_by_major = {}
            for major_id, ey in bindings:
                year_by_major.setdefault(major_id, set()).add(ey)

            conditions = []
            for major_id, ey_set in year_by_major.items():
                if None in ey_set:
                    conditions.append(OrganizationMember.organization_id == major_id)
                else:
                    conditions.append(
                        and_(
                            OrganizationMember.organization_id == major_id,
                            User.enrollment_year.in_(ey_set)
                        )
                    )

            stmt = (
                select(User, OrganizationMember.organization_id)
                .join(OrganizationMember, OrganizationMember.user_id == User.id)
                .where(
                    or_(*conditions),
                    OrganizationMember.status == "active",
                    User.role == "student",
                    User.status == "active"
                )
            )
            result = await session.execute(stmt)
            rows = result.unique().all()

            for user, org_id in rows:
                if user.id not in seen:
                    seen.add(user.id)
                    students.append({
                        "id": user.id,
                        "name": user.name,
                        "student_id": user.student_id,
                        "enrollment_year": user.enrollment_year,
                        "major_name": major_name_map.get(org_id),
                        "source": "major",
                    })

        try:
            direct_stmt = (
                select(TeachingSpaceStudent)
                .options(joinedload(TeachingSpaceStudent.student))
                .where(TeachingSpaceStudent.space_id == space_id)
            )
            direct_res = await session.execute(direct_stmt)
            direct_bindings = direct_res.scalars().unique().all()
            for binding in direct_bindings:
                if binding.student_id not in seen:
                    seen.add(binding.student_id)
                    stu = binding.student
                    students.append({
                        "id": binding.student_id,
                        "name": stu.name if stu else None,
                        "student_id": stu.student_id if stu else None,
                        "enrollment_year": stu.enrollment_year if stu else None,
                        "major_name": None,
                        "source": "direct",
                    })
        except Exception as e:
            logger.warning(f"查询直接添加的学生失败（teaching_space_student 表可能未创建）: {e}")

        return students

    @staticmethod
    async def add_student(session: AsyncSession, space_id: int, student_id: int, operator_id: int, user_role: str = "teacher") -> dict:
        space_stmt = select(TeachingSpace).where(TeachingSpace.id == space_id)
        space_res = await session.execute(space_stmt)
        space = space_res.scalars().first()
        if not space:
            raise NotFoundError("教学空间不存在")
        if user_role != "admin" and space.teacher_id != operator_id:
            raise ForbiddenError("无权操作此教学空间")

        student_stmt = select(User).where(User.id == student_id, User.role == "student", User.status == "active")
        student_res = await session.execute(student_stmt)
        student = student_res.scalars().first()
        if not student:
            raise ValidationError("学生不存在或状态异常")

        existing_stmt = select(TeachingSpaceStudent).where(
            TeachingSpaceStudent.space_id == space_id,
            TeachingSpaceStudent.student_id == student_id
        )
        existing_res = await session.execute(existing_stmt)
        if existing_res.scalars().first():
            raise ValidationError("该学生已在此空间中")

        binding = TeachingSpaceStudent(space_id=space_id, student_id=student_id)
        session.add(binding)
        await session.commit()
        await session.refresh(binding)
        return {"id": binding.id, "space_id": space_id, "student_id": student_id, "student_name": student.name}

    @staticmethod
    async def remove_student(session: AsyncSession, space_id: int, student_id: int, operator_id: int, user_role: str = "teacher") -> bool:
        space_stmt = select(TeachingSpace).where(TeachingSpace.id == space_id)
        space_res = await session.execute(space_stmt)
        space = space_res.scalars().first()
        if not space:
            raise NotFoundError("教学空间不存在")
        if user_role != "admin" and space.teacher_id != operator_id:
            raise ForbiddenError("无权操作此教学空间")

        stmt = delete(TeachingSpaceStudent).where(
            TeachingSpaceStudent.space_id == space_id,
            TeachingSpaceStudent.student_id == student_id
        )
        result = await session.execute(stmt)
        await session.commit()
        if result.rowcount == 0:
            raise ValidationError("该学生不在此空间中（或是通过专业绑定加入的，需解绑专业）")
        return True

    @staticmethod
    async def publish_resource(session: AsyncSession, space_id: int, teacher_id: int, resource_type: str, resource_id: int, user_role: str = "teacher") -> dict:
        space_stmt = select(TeachingSpace).where(TeachingSpace.id == space_id)
        space_res = await session.execute(space_stmt)
        space = space_res.scalars().first()
        if not space:
            raise NotFoundError("教学空间不存在")
        if user_role != "admin" and space.teacher_id != teacher_id:
            raise ForbiddenError("无权操作此教学空间")

        if resource_type not in ("vector_db", "bot"):
            raise ValidationError("资源类型必须是 vector_db 或 bot")

        if user_role == "admin":
            if resource_type == "vector_db":
                res_stmt = select(VectorDb).where(VectorDb.id == resource_id)
            else:
                res_stmt = select(Bot).where(Bot.id == resource_id)
        else:
            if resource_type == "vector_db":
                res_stmt = select(VectorDb).where(VectorDb.id == resource_id, VectorDb.user_id == teacher_id)
            else:
                res_stmt = select(Bot).where(Bot.id == resource_id, Bot.user_id == teacher_id)
        res_result = await session.execute(res_stmt)
        if not res_result.scalars().first():
            raise ValidationError("资源不存在或不属于你")

        existing_stmt = select(TeachingSpaceResource).where(
            TeachingSpaceResource.space_id == space_id,
            TeachingSpaceResource.resource_type == resource_type,
            TeachingSpaceResource.resource_id == resource_id
        )
        existing_res = await session.execute(existing_stmt)
        if existing_res.scalars().first():
            raise ValidationError("该资源已分发到此空间")

        resource = TeachingSpaceResource(space_id=space_id, resource_type=resource_type, resource_id=resource_id)
        session.add(resource)
        await session.commit()
        await session.refresh(resource)
        return resource.to_dict()

    @staticmethod
    async def unpublish_resource(session: AsyncSession, space_id: int, teacher_id: int, resource_type: str, resource_id: int, user_role: str = "teacher") -> bool:
        space_stmt = select(TeachingSpace).where(TeachingSpace.id == space_id)
        space_res = await session.execute(space_stmt)
        space = space_res.scalars().first()
        if not space:
            raise NotFoundError("教学空间不存在")
        if user_role != "admin" and space.teacher_id != teacher_id:
            raise ForbiddenError("无权操作此教学空间")

        stmt = delete(TeachingSpaceResource).where(
            TeachingSpaceResource.space_id == space_id,
            TeachingSpaceResource.resource_type == resource_type,
            TeachingSpaceResource.resource_id == resource_id
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount > 0

    @staticmethod
    async def get_space_resources(session: AsyncSession, space_id: int) -> dict:
        """获取空间内的所有资源，按类型分组并附带详情"""
        stmt = select(TeachingSpaceResource).where(TeachingSpaceResource.space_id == space_id)
        result = await session.execute(stmt)
        resources = result.scalars().all()

        vector_db_ids = [r.resource_id for r in resources if r.resource_type == "vector_db"]
        bot_ids = [r.resource_id for r in resources if r.resource_type == "bot"]

        vector_dbs = []
        if vector_db_ids:
            vdb_stmt = select(VectorDb).options(
                selectinload(VectorDb.user), selectinload(VectorDb.organization)
            ).where(VectorDb.id.in_(vector_db_ids))
            vdb_res = await session.execute(vdb_stmt)
            vector_dbs = [vdb.to_dict() for vdb in vdb_res.scalars().all()]

        bots = []
        if bot_ids:
            bot_stmt = select(Bot).options(
                selectinload(Bot.user), selectinload(Bot.organization)
            ).where(Bot.id.in_(bot_ids))
            bot_res = await session.execute(bot_stmt)
            bots = [b.to_dict() for b in bot_res.scalars().all()]

        return {"vector_dbs": vector_dbs, "bots": bots}

    @staticmethod
    async def get_student_space_resources(session: AsyncSession, student_id: int, space_id: int, resource_type: Optional[str] = None) -> dict:
        """验证学生属于该空间后返回资源"""
        student_major_stmt = (
            select(OrganizationMember.organization_id)
            .join(Organization, Organization.id == OrganizationMember.organization_id)
            .where(
                OrganizationMember.user_id == student_id,
                OrganizationMember.status == "active",
                Organization.type == "major"
            )
        )
        student_major_res = await session.execute(student_major_stmt)
        student_major_ids = set(row[0] for row in student_major_res.all())

        space_major_stmt = select(TeachingSpaceMajor.major_id).where(TeachingSpaceMajor.space_id == space_id)
        space_major_res = await session.execute(space_major_stmt)
        space_major_ids = set(row[0] for row in space_major_res.all())

        if not student_major_ids.intersection(space_major_ids):
            direct_stmt = select(TeachingSpaceStudent).where(
                TeachingSpaceStudent.space_id == space_id,
                TeachingSpaceStudent.student_id == student_id
            )
            direct_res = await session.execute(direct_stmt)
            if not direct_res.scalars().first():
                raise ForbiddenError("你不属于此教学空间")

        return await AsyncTeachingSpaceService.get_space_resources(session, space_id)
