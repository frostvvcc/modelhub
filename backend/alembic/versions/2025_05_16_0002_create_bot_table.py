"""create bot table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2025-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'bot',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False, comment='Bot 名称'),
        sa.Column('description', sa.Text(), nullable=True, comment='Bot 描述'),
        sa.Column('avatar', sa.String(length=255), nullable=True, comment='Bot 头像 URL'),
        sa.Column('system_prompt', sa.Text(), nullable=True, comment='系统提示词（人设/角色设定）'),
        sa.Column('greeting', sa.String(length=500), nullable=True, comment='开场白'),
        sa.Column('forbidden_topics', sa.JSON(), nullable=True, comment='禁止话题列表'),
        sa.Column('model_config_id', sa.Integer(), nullable=True, comment='关联模型配置'),
        sa.Column('vector_db_ids', sa.JSON(), nullable=True, comment='关联知识库 ID 列表'),
        sa.Column('visibility', sa.String(length=20), nullable=False, server_default='private', comment='可见范围：public/organization/private'),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='创建者'),
        sa.Column('org_id', sa.Integer(), nullable=True, comment='所属组织'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['model_config_id'], ['model_config.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_bot_user_id', 'bot', ['user_id'], unique=False)
    op.create_index('idx_bot_visibility', 'bot', ['visibility'], unique=False)
    op.create_index('idx_bot_org_id', 'bot', ['org_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_bot_org_id', table_name='bot')
    op.drop_index('idx_bot_visibility', table_name='bot')
    op.drop_index('idx_bot_user_id', table_name='bot')
    op.drop_table('bot')
