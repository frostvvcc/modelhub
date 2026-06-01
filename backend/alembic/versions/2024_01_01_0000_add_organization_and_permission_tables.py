"""add_organization_and_permission_tables

Revision ID: 001_add_org_perm
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '001_add_org_perm'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 创建组织架构表
    op.create_table(
        'organization',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False, comment='组织名称'),
        sa.Column('code', sa.String(length=100), nullable=False, comment='组织编码（唯一）'),
        sa.Column('type', sa.String(length=50), nullable=False, comment='组织类型：school/college/department/class/research_group/lab'),
        sa.Column('parent_id', sa.Integer(), nullable=True, comment='父组织ID（自关联）'),
        sa.Column('school_id', sa.Integer(), nullable=True, comment='所属学校ID（根节点）'),
        sa.Column('level', sa.Integer(), nullable=False, server_default='1', comment='层级深度（1=学校, 2=学院, 3=系, 4=班级等）'),
        sa.Column('path', sa.String(length=500), nullable=True, comment='路径字符串（如：1/2/5，便于查询）'),
        sa.Column('description', sa.String(length=500), nullable=True, comment='描述'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active', comment='状态：active/inactive/suspended'),
        sa.Column('create_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('update_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['parent_id'], ['organization.id'], ),
        sa.ForeignKeyConstraint(['school_id'], ['organization.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    op.create_index('idx_organization_parent_id', 'organization', ['parent_id'], unique=False)
    op.create_index('idx_organization_school_id', 'organization', ['school_id'], unique=False)
    op.create_index('idx_organization_type', 'organization', ['type'], unique=False)
    op.create_index('idx_organization_path', 'organization', ['path'], unique=False, mysql_length=255)
    op.create_index('idx_organization_school_type', 'organization', ['school_id', 'type'], unique=False)
    op.create_index('idx_organization_status', 'organization', ['status'], unique=False)
    
    # 创建组织成员表
    op.create_table(
        'organization_member',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='用户ID'),
        sa.Column('organization_id', sa.Integer(), nullable=False, comment='组织ID'),
        sa.Column('role', sa.String(length=50), nullable=False, server_default='member', comment='角色：admin/teacher/student/guest/member'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active', comment='状态：active/inactive'),
        sa.Column('join_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False, comment='加入时间'),
        sa.Column('create_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('update_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_org_member_user_id', 'organization_member', ['user_id'], unique=False)
    op.create_index('idx_org_member_organization_id', 'organization_member', ['organization_id'], unique=False)
    op.create_index('idx_org_member_user_org', 'organization_member', ['user_id', 'organization_id'], unique=False)
    op.create_index('idx_org_member_org_role', 'organization_member', ['organization_id', 'role'], unique=False)
    
    # 创建角色表
    op.create_table(
        'role',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False, comment='角色名称'),
        sa.Column('code', sa.String(length=100), nullable=False, comment='角色代码（唯一）'),
        sa.Column('description', sa.String(length=500), nullable=True, comment='描述'),
        sa.Column('level', sa.String(length=50), nullable=False, server_default='class', comment='权限级别：system/school/college/department/class'),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='0', comment='是否系统角色'),
        sa.Column('school_id', sa.Integer(), nullable=True, comment='所属学校（系统角色为NULL）'),
        sa.Column('create_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('update_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['school_id'], ['organization.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    op.create_index('idx_role_code', 'role', ['code'], unique=False)
    op.create_index('idx_role_level', 'role', ['level'], unique=False)
    op.create_index('idx_role_school_id', 'role', ['school_id'], unique=False)
    op.create_index('idx_role_is_system', 'role', ['is_system'], unique=False)
    
    # 创建权限表
    op.create_table(
        'permission',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False, comment='权限名称'),
        sa.Column('code', sa.String(length=100), nullable=False, comment='权限代码（唯一，如：knowledge:read）'),
        sa.Column('description', sa.String(length=500), nullable=True, comment='描述'),
        sa.Column('resource', sa.String(length=50), nullable=False, comment='资源类型：knowledge/chat/config/user/organization等'),
        sa.Column('action', sa.String(length=50), nullable=False, comment='操作类型：read/write/delete/manage'),
        sa.Column('create_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('update_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    op.create_index('idx_permission_code', 'permission', ['code'], unique=False)
    op.create_index('idx_permission_resource', 'permission', ['resource'], unique=False)
    op.create_index('idx_permission_action', 'permission', ['action'], unique=False)
    op.create_index('idx_permission_resource_action', 'permission', ['resource', 'action'], unique=False)
    
    # 创建角色权限关联表
    op.create_table(
        'role_permission',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False, comment='角色ID'),
        sa.Column('permission_id', sa.Integer(), nullable=False, comment='权限ID'),
        sa.Column('create_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['permission_id'], ['permission.id'], ),
        sa.ForeignKeyConstraint(['role_id'], ['role.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_id', 'permission_id', name='uq_role_permission')
    )
    op.create_index('idx_role_permission_role_id', 'role_permission', ['role_id'], unique=False)
    op.create_index('idx_role_permission_permission_id', 'role_permission', ['permission_id'], unique=False)
    
    # 创建用户角色关联表
    op.create_table(
        'user_role',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='用户ID'),
        sa.Column('role_id', sa.Integer(), nullable=False, comment='角色ID'),
        sa.Column('organization_id', sa.Integer(), nullable=True, comment='组织ID（可选，用于组织级角色）'),
        sa.Column('scope', sa.String(length=50), nullable=True, comment='作用域：system/school/college/department/class'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1', comment='是否激活'),
        sa.Column('create_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('update_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], ),
        sa.ForeignKeyConstraint(['role_id'], ['role.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_user_role_user_id', 'user_role', ['user_id'], unique=False)
    op.create_index('idx_user_role_role_id', 'user_role', ['role_id'], unique=False)
    op.create_index('idx_user_role_organization_id', 'user_role', ['organization_id'], unique=False)
    op.create_index('idx_user_role_user_org_role', 'user_role', ['user_id', 'organization_id', 'role_id'], unique=False)
    op.create_index('idx_user_role_is_active', 'user_role', ['is_active'], unique=False)
    
    # 修改用户表，添加新字段
    op.add_column('user', sa.Column('school_id', sa.Integer(), nullable=True, comment='所属学校ID'))
    op.add_column('user', sa.Column('student_id', sa.String(length=50), nullable=True, comment='学号'))
    op.add_column('user', sa.Column('employee_id', sa.String(length=50), nullable=True, comment='工号'))
    op.add_column('user', sa.Column('phone', sa.String(length=20), nullable=True, comment='手机号'))
    op.add_column('user', sa.Column('status', sa.String(length=20), nullable=False, server_default='active', comment='用户状态：active/inactive/suspended'))
    op.create_foreign_key('fk_user_school_id', 'user', 'organization', ['school_id'], ['id'])
    op.create_index('idx_user_school_id', 'user', ['school_id'], unique=False)
    op.create_index('idx_user_student_id', 'user', ['student_id'], unique=False)
    op.create_index('idx_user_employee_id', 'user', ['employee_id'], unique=False)
    op.create_index('idx_user_status', 'user', ['status'], unique=False)
    
    # 修改向量数据库表，添加新字段
    op.add_column('vector_db', sa.Column('organization_id', sa.Integer(), nullable=True, comment='所属组织ID'))
    op.add_column('vector_db', sa.Column('school_id', sa.Integer(), nullable=True, comment='所属学校ID（冗余字段，便于查询）'))
    op.add_column('vector_db', sa.Column('scope', sa.String(length=20), nullable=False, server_default='private', comment='可见范围：public/organization/private'))
    op.add_column('vector_db', sa.Column('access_level', sa.String(length=20), nullable=True, comment='访问级别：school/college/department/class'))
    op.create_foreign_key('fk_vector_db_organization_id', 'vector_db', 'organization', ['organization_id'], ['id'])
    op.create_foreign_key('fk_vector_db_school_id', 'vector_db', 'organization', ['school_id'], ['id'])
    op.create_index('idx_vector_db_organization_id', 'vector_db', ['organization_id'], unique=False)
    op.create_index('idx_vector_db_school_id', 'vector_db', ['school_id'], unique=False)
    op.create_index('idx_vector_db_scope', 'vector_db', ['scope'], unique=False)
    op.create_index('idx_vector_db_org_scope', 'vector_db', ['organization_id', 'scope'], unique=False)
    
    # 修改对话表，添加新字段
    op.add_column('conversation', sa.Column('organization_id', sa.Integer(), nullable=True, comment='所属组织ID'))
    op.add_column('conversation', sa.Column('school_id', sa.Integer(), nullable=True, comment='所属学校ID'))
    op.create_foreign_key('fk_conversation_organization_id', 'conversation', 'organization', ['organization_id'], ['id'])
    op.create_foreign_key('fk_conversation_school_id', 'conversation', 'organization', ['school_id'], ['id'])
    op.create_index('idx_conversation_organization_id', 'conversation', ['organization_id'], unique=False)
    op.create_index('idx_conversation_school_id', 'conversation', ['school_id'], unique=False)
    
    # 修改模型配置表，添加新字段
    op.add_column('model_config', sa.Column('organization_id', sa.Integer(), nullable=True, comment='所属组织ID'))
    op.add_column('model_config', sa.Column('school_id', sa.Integer(), nullable=True, comment='所属学校ID'))
    op.add_column('model_config', sa.Column('scope', sa.String(length=20), nullable=False, server_default='private', comment='可见范围：public/organization/private'))
    op.create_foreign_key('fk_model_config_organization_id', 'model_config', 'organization', ['organization_id'], ['id'])
    op.create_foreign_key('fk_model_config_school_id', 'model_config', 'organization', ['school_id'], ['id'])
    op.create_index('idx_model_config_organization_id', 'model_config', ['organization_id'], unique=False)
    op.create_index('idx_model_config_school_id', 'model_config', ['school_id'], unique=False)
    op.create_index('idx_model_config_scope', 'model_config', ['scope'], unique=False)


def downgrade() -> None:
    # 删除模型配置表的新字段和索引
    op.drop_index('idx_model_config_scope', table_name='model_config')
    op.drop_index('idx_model_config_school_id', table_name='model_config')
    op.drop_index('idx_model_config_organization_id', table_name='model_config')
    op.drop_constraint('fk_model_config_school_id', 'model_config', type_='foreignkey')
    op.drop_constraint('fk_model_config_organization_id', 'model_config', type_='foreignkey')
    op.drop_column('model_config', 'scope')
    op.drop_column('model_config', 'school_id')
    op.drop_column('model_config', 'organization_id')
    
    # 删除对话表的新字段和索引
    op.drop_index('idx_conversation_school_id', table_name='conversation')
    op.drop_index('idx_conversation_organization_id', table_name='conversation')
    op.drop_constraint('fk_conversation_school_id', 'conversation', type_='foreignkey')
    op.drop_constraint('fk_conversation_organization_id', 'conversation', type_='foreignkey')
    op.drop_column('conversation', 'school_id')
    op.drop_column('conversation', 'organization_id')
    
    # 删除向量数据库表的新字段和索引
    op.drop_index('idx_vector_db_org_scope', table_name='vector_db')
    op.drop_index('idx_vector_db_scope', table_name='vector_db')
    op.drop_index('idx_vector_db_school_id', table_name='vector_db')
    op.drop_index('idx_vector_db_organization_id', table_name='vector_db')
    op.drop_constraint('fk_vector_db_school_id', 'vector_db', type_='foreignkey')
    op.drop_constraint('fk_vector_db_organization_id', 'vector_db', type_='foreignkey')
    op.drop_column('vector_db', 'access_level')
    op.drop_column('vector_db', 'scope')
    op.drop_column('vector_db', 'school_id')
    op.drop_column('vector_db', 'organization_id')
    
    # 删除用户表的新字段和索引
    op.drop_index('idx_user_status', table_name='user')
    op.drop_index('idx_user_employee_id', table_name='user')
    op.drop_index('idx_user_student_id', table_name='user')
    op.drop_index('idx_user_school_id', table_name='user')
    op.drop_constraint('fk_user_school_id', 'user', type_='foreignkey')
    op.drop_column('user', 'status')
    op.drop_column('user', 'phone')
    op.drop_column('user', 'employee_id')
    op.drop_column('user', 'student_id')
    op.drop_column('user', 'school_id')
    
    # 删除用户角色关联表
    op.drop_index('idx_user_role_is_active', table_name='user_role')
    op.drop_index('idx_user_role_user_org_role', table_name='user_role')
    op.drop_index('idx_user_role_organization_id', table_name='user_role')
    op.drop_index('idx_user_role_role_id', table_name='user_role')
    op.drop_index('idx_user_role_user_id', table_name='user_role')
    op.drop_table('user_role')
    
    # 删除角色权限关联表
    op.drop_index('idx_role_permission_permission_id', table_name='role_permission')
    op.drop_index('idx_role_permission_role_id', table_name='role_permission')
    op.drop_table('role_permission')
    
    # 删除权限表
    op.drop_index('idx_permission_resource_action', table_name='permission')
    op.drop_index('idx_permission_action', table_name='permission')
    op.drop_index('idx_permission_resource', table_name='permission')
    op.drop_index('idx_permission_code', table_name='permission')
    op.drop_table('permission')
    
    # 删除角色表
    op.drop_index('idx_role_is_system', table_name='role')
    op.drop_index('idx_role_school_id', table_name='role')
    op.drop_index('idx_role_level', table_name='role')
    op.drop_index('idx_role_code', table_name='role')
    op.drop_table('role')
    
    # 删除组织成员表
    op.drop_index('idx_org_member_org_role', table_name='organization_member')
    op.drop_index('idx_org_member_user_org', table_name='organization_member')
    op.drop_index('idx_org_member_organization_id', table_name='organization_member')
    op.drop_index('idx_org_member_user_id', table_name='organization_member')
    op.drop_table('organization_member')
    
    # 删除组织架构表
    op.drop_index('idx_organization_status', table_name='organization')
    op.drop_index('idx_organization_school_type', table_name='organization')
    op.drop_index('idx_organization_path', table_name='organization')
    op.drop_index('idx_organization_type', table_name='organization')
    op.drop_index('idx_organization_school_id', table_name='organization')
    op.drop_index('idx_organization_parent_id', table_name='organization')
    op.drop_table('organization')

