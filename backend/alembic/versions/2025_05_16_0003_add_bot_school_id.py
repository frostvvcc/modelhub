"""add bot.school_id

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2025-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bot', sa.Column('school_id', sa.Integer(), nullable=True, comment='所属学校（冗余，便于查询）'))
    op.create_foreign_key('fk_bot_school_id', 'bot', 'organization', ['school_id'], ['id'])
    op.create_index('idx_bot_school_id', 'bot', ['school_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_bot_school_id', table_name='bot')
    op.drop_constraint('fk_bot_school_id', 'bot', type_='foreignkey')
    op.drop_column('bot', 'school_id')
