#!/usr/bin/env python3
"""
初始化示例数据
创建默认学校、组织、角色、权限和测试用户
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database_async import async_engine, AsyncSessionLocal
from app.models import *
from app.mappers.organization_mapper import AsyncOrganizationMapper
from app.mappers.permission_mapper import AsyncPermissionMapper
from app.mappers.user_mapper import AsyncUserMapper
from app.utils.logger_config import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def create_virtual_organizations(session):
    """创建虚拟组织架构"""
    logger.info("创建虚拟组织架构...")
    
    virtual_orgs = {}
    virtual_schools = [
        {"name": "虚拟公开学校", "code": "VIRTUAL_PUBLIC", "type": "school", "description": "公开权限虚拟学校"},
        {"name": "虚拟教师学校", "code": "VIRTUAL_TEACHER", "type": "school", "description": "教师权限虚拟学校"},
        {"name": "虚拟私有学校", "code": "VIRTUAL_PRIVATE", "type": "school", "description": "私有权限虚拟学校"}
    ]
    
    for school_data in virtual_schools:
        org = await AsyncOrganizationMapper.get_organization_by_code(session, school_data["code"])
        if not org:
            org = await AsyncOrganizationMapper.create_organization(
                session,
                name=school_data["name"],
                code=school_data["code"],
                org_type=school_data["type"],
                parent_id=None,
                school_id=None,
                level=1,
                path=None,
                description=school_data["description"],
                status="active"
            )
            # 更新路径
            await AsyncOrganizationMapper.update_organization(
                session, org.id, path=str(org.id)
            )
            logger.info(f"✅ 创建虚拟组织: {org.name} (ID: {org.id})")
        else:
            logger.info(f"✅ 虚拟组织已存在: {org.name}")
        virtual_orgs[school_data["code"]] = org
    
    return virtual_orgs


async def init_sample_data():
    """初始化示例数据"""
    async with AsyncSessionLocal() as db:
        try:
            # 1. 创建虚拟组织架构
            virtual_orgs = await create_virtual_organizations(db)
            
            # 2. 创建默认学校（保持兼容性）
            logger.info("创建默认学校...")
            school = await AsyncOrganizationMapper.get_organization_by_code(db, "DEFAULT_SCHOOL")
            if not school:
                school = await AsyncOrganizationMapper.create_organization(
                    db,
                    name="山东科技大学",
                    code="DEFAULT_SCHOOL",
                    org_type="school",
                    parent_id=None,
                    school_id=None,
                    level=1,
                    path=None,
                    description="山东科技大学",
                    status="active"
                )
                # 更新路径
                await AsyncOrganizationMapper.update_organization(
                    db, school.id, path=str(school.id)
                )
                logger.info(f"✅ 创建学校: {school.name} (ID: {school.id})")
            else:
                logger.info(f"✅ 学校已存在: {school.name}")

            # 2. 创建学院
            logger.info("创建示例学院...")
            college = await AsyncOrganizationMapper.get_organization_by_code(db, "CS_COLLEGE")
            if not college:
                college = await AsyncOrganizationMapper.create_organization(
                    db,
                    name="计算机学院",
                    code="CS_COLLEGE",
                    org_type="college",
                    parent_id=school.id,
                    school_id=school.id,
                    level=2,
                    path=f"{school.id}",
                    description="计算机科学与技术学院",
                    status="active"
                )
                await AsyncOrganizationMapper.update_organization(
                    db, college.id, path=f"{school.id}/{college.id}"
                )
                logger.info(f"✅ 创建学院: {college.name} (ID: {college.id})")
            else:
                logger.info(f"✅ 学院已存在: {college.name}")

            # 3. 创建系
            logger.info("创建示例系...")
            department = await AsyncOrganizationMapper.get_organization_by_code(db, "CS_DEPT")
            if not department:
                department = await AsyncOrganizationMapper.create_organization(
                    db,
                    name="计算机科学系",
                    code="CS_DEPT",
                    org_type="department",
                    parent_id=college.id,
                    school_id=school.id,
                    level=3,
                    path=f"{school.id}/{college.id}",
                    description="计算机科学系",
                    status="active"
                )
                await AsyncOrganizationMapper.update_organization(
                    db, department.id, path=f"{school.id}/{college.id}/{department.id}"
                )
                logger.info(f"✅ 创建系: {department.name} (ID: {department.id})")
            else:
                logger.info(f"✅ 系已存在: {department.name}")

            # 4. 创建班级
            logger.info("创建示例班级...")
            class_org = await AsyncOrganizationMapper.get_organization_by_code(db, "CS_CLASS_2024")
            if not class_org:
                class_org = await AsyncOrganizationMapper.create_organization(
                    db,
                    name="2024级计算机1班",
                    code="CS_CLASS_2024",
                    org_type="class",
                    parent_id=department.id,
                    school_id=school.id,
                    level=4,
                    path=f"{school.id}/{college.id}/{department.id}",
                    description="2024级计算机科学1班",
                    status="active"
                )
                await AsyncOrganizationMapper.update_organization(
                    db, class_org.id, path=f"{school.id}/{college.id}/{department.id}/{class_org.id}"
                )
                logger.info(f"✅ 创建班级: {class_org.name} (ID: {class_org.id})")
            else:
                logger.info(f"✅ 班级已存在: {class_org.name}")

            # 5. 创建默认权限
            logger.info("创建默认权限...")
            permissions = [
                {"code": "user:read", "name": "查看用户", "resource": "user", "action": "read", "description": "查看用户信息"},
                {"code": "user:write", "name": "管理用户", "resource": "user", "action": "write", "description": "创建和编辑用户"},
                {"code": "organization:read", "name": "查看组织", "resource": "organization", "action": "read", "description": "查看组织信息"},
                {"code": "organization:write", "name": "管理组织", "resource": "organization", "action": "write", "description": "创建和编辑组织"},
                {"code": "knowledge:read", "name": "查看知识库", "resource": "knowledge", "action": "read", "description": "查看知识库"},
                {"code": "knowledge:write", "name": "管理知识库", "resource": "knowledge", "action": "write", "description": "创建和编辑知识库"},
                {"code": "chat:read", "name": "使用对话", "resource": "chat", "action": "read", "description": "使用对话功能"},
                {"code": "chat:write", "name": "管理对话", "resource": "chat", "action": "write", "description": "创建和管理对话"},
                {"code": "config:read", "name": "查看配置", "resource": "config", "action": "read", "description": "查看模型配置"},
                {"code": "config:write", "name": "管理配置", "resource": "config", "action": "write", "description": "创建和编辑模型配置"},
                {"code": "permission:read", "name": "查看权限", "resource": "permission", "action": "read", "description": "查看权限信息"},
                {"code": "permission:write", "name": "管理权限", "resource": "permission", "action": "write", "description": "管理权限和角色"},
            ]

            permission_map = {}
            for perm_data in permissions:
                perm = await AsyncPermissionMapper.get_permission_by_code(db, perm_data["code"])
                if not perm:
                    perm = await AsyncPermissionMapper.create_permission(
                        db,
                        name=perm_data["name"],
                        code=perm_data["code"],
                        description=perm_data["description"],
                        resource=perm_data["resource"],
                        action=perm_data["action"]
                    )
                    logger.info(f"✅ 创建权限: {perm.code}")
                else:
                    logger.info(f"✅ 权限已存在: {perm.code}")
                permission_map[perm_data["code"]] = perm

            # 6. 创建默认角色
            logger.info("创建默认角色...")
            
            # 系统管理员角色
            admin_role = await AsyncPermissionMapper.get_role_by_code(db, "system_admin")
            if not admin_role:
                admin_role = await AsyncPermissionMapper.create_role(
                    db,
                    name="系统管理员",
                    code="system_admin",
                    description="系统管理员，拥有所有权限",
                    level="system",
                    is_system=True,
                    school_id=None
                )
                # 分配所有权限
                for perm in permission_map.values():
                    try:
                        await AsyncPermissionMapper.assign_permission_to_role(db, admin_role.id, perm.id)
                    except:
                        pass
                logger.info(f"✅ 创建角色: {admin_role.name}")
            else:
                logger.info(f"✅ 角色已存在: {admin_role.name}")

            # 学校管理员角色
            school_admin_role = await AsyncPermissionMapper.get_role_by_code(db, "school_admin")
            if not school_admin_role:
                school_admin_role = await AsyncPermissionMapper.create_role(
                    db,
                    name="学校管理员",
                    code="school_admin",
                    description="学校管理员，管理学校内所有资源",
                    level="school",
                    is_system=False,
                    school_id=school.id
                )
                # 分配学校级权限
                school_perms = ["user:read", "user:write", "organization:read", "organization:write",
                               "knowledge:read", "knowledge:write", "chat:read", "chat:write",
                               "config:read", "config:write", "permission:read"]
                for perm_code in school_perms:
                    if perm_code in permission_map:
                        try:
                            await AsyncPermissionMapper.assign_permission_to_role(
                                db, school_admin_role.id, permission_map[perm_code].id
                            )
                        except:
                            pass
                logger.info(f"✅ 创建角色: {school_admin_role.name}")
            else:
                logger.info(f"✅ 角色已存在: {school_admin_role.name}")

            # 教师角色
            teacher_role = await AsyncPermissionMapper.get_role_by_code(db, "teacher")
            if not teacher_role:
                teacher_role = await AsyncPermissionMapper.create_role(
                    db,
                    name="教师",
                    code="teacher",
                    description="教师角色，可以管理班级和学生",
                    level="class",
                    is_system=False,
                    school_id=school.id
                )
                # 分配教师权限
                teacher_perms = ["user:read", "organization:read", "knowledge:read", "knowledge:write",
                               "chat:read", "chat:write"]
                for perm_code in teacher_perms:
                    if perm_code in permission_map:
                        try:
                            await AsyncPermissionMapper.assign_permission_to_role(
                                db, teacher_role.id, permission_map[perm_code].id
                            )
                        except:
                            pass
                logger.info(f"✅ 创建角色: {teacher_role.name}")
            else:
                logger.info(f"✅ 角色已存在: {teacher_role.name}")

            # 学生角色
            student_role = await AsyncPermissionMapper.get_role_by_code(db, "student")
            if not student_role:
                student_role = await AsyncPermissionMapper.create_role(
                    db,
                    name="学生",
                    code="student",
                    description="学生角色，基础使用权限",
                    level="class",
                    is_system=False,
                    school_id=school.id
                )
                # 分配学生权限
                student_perms = ["user:read", "organization:read", "knowledge:read",
                               "chat:read", "chat:write", "config:read"]
                for perm_code in student_perms:
                    if perm_code in permission_map:
                        try:
                            await AsyncPermissionMapper.assign_permission_to_role(
                                db, student_role.id, permission_map[perm_code].id
                            )
                        except:
                            pass
                logger.info(f"✅ 创建角色: {student_role.name}")
            else:
                logger.info(f"✅ 角色已存在: {student_role.name}")

            # 7. 创建测试用户
            logger.info("创建测试用户...")
            
            test_users = [
                {
                    "name": "系统管理员",
                    "email": "admin@example.com",
                    "password": "admin123",
                    "student_id": None,
                    "employee_id": "E001",
                    "school_id": school.id,
                    "role_code": "system_admin",
                    "virtual_org_code": "VIRTUAL_PUBLIC"  # 管理员可以访问所有
                },
                {
                    "name": "学校管理员",
                    "email": "school_admin@example.com",
                    "password": "admin123",
                    "student_id": None,
                    "employee_id": "E002",
                    "school_id": school.id,
                    "role_code": "school_admin",
                    "virtual_org_code": "VIRTUAL_PUBLIC"  # 管理员可以访问所有
                },
                {
                    "name": "张老师",
                    "email": "teacher1@example.com",
                    "password": "teacher123",
                    "student_id": None,
                    "employee_id": "T001",
                    "school_id": school.id,
                    "role_code": "teacher",
                    "virtual_org_code": "VIRTUAL_TEACHER"  # 教师分配到教师虚拟组织
                },
                {
                    "name": "李同学",
                    "email": "student1@example.com",
                    "password": "student123",
                    "student_id": "S2024001",
                    "employee_id": None,
                    "school_id": school.id,
                    "role_code": "student",
                    "virtual_org_code": "VIRTUAL_PUBLIC"  # 学生分配到公开虚拟组织
                },
            ]

            for user_data in test_users:
                # 检查用户是否存在
                existing_user = await AsyncUserMapper.get_user_by_email(db, user_data["email"])
                if not existing_user:
                    # 创建用户
                    user = await AsyncUserMapper.create_user(
                        db,
                        name=user_data["name"],
                        email=user_data["email"],
                        password=user_data["password"],
                        school_id=user_data["school_id"],
                        student_id=user_data["student_id"],
                        employee_id=user_data["employee_id"]
                    )
                    
                    # 分配角色
                    role = await AsyncPermissionMapper.get_role_by_code(db, user_data["role_code"])
                    if role:
                        await AsyncPermissionMapper.assign_role_to_user(
                            db, user.id, role.id, school.id, "school"
                        )
                    
                    # 添加到虚拟组织（简化权限系统的关键）
                    virtual_org = virtual_orgs[user_data["virtual_org_code"]]
                    await AsyncOrganizationMapper.add_member(
                        db, user.id, virtual_org.id, user_data["role_code"]
                    )
                    
                    # 同时保持原有组织关系（兼容性）
                    if user_data["role_code"] == "student":
                        await AsyncOrganizationMapper.add_member(
                            db, user.id, class_org.id, "student"
                        )
                    elif user_data["role_code"] == "teacher":
                        await AsyncOrganizationMapper.add_member(
                            db, user.id, department.id, "teacher"
                        )
                    
                    logger.info(f"✅ 创建用户: {user.name} ({user.email}) -> 虚拟组织: {virtual_org.name}")
                else:
                    logger.info(f"✅ 用户已存在: {user_data['name']}")

            await db.commit()
            logger.info("")
            logger.info("=" * 50)
            logger.info("✅ 示例数据初始化完成！")
            logger.info("=" * 50)
            logger.info("")
            logger.info("测试账号:")
            logger.info("  系统管理员: admin@example.com / admin123")
            logger.info("  学校管理员: school_admin@example.com / admin123")
            logger.info("  教师: teacher1@example.com / teacher123")
            logger.info("  学生: student1@example.com / student123")
            logger.info("")

        except Exception as e:
            await db.rollback()
            logger.error(f"初始化失败: {str(e)}", exc_info=True)
            raise


if __name__ == "__main__":
    asyncio.run(init_sample_data())

