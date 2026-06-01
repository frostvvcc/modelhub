"""add teaching_space.space_code

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2025-05-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('teaching_space', sa.Column('space_code', sa.String(20), nullable=True, comment='结构化编号，如 CS-25-001'))
    op.create_index('idx_teaching_space_code', 'teaching_space', ['space_code'], unique=True)


def downgrade() -> None:
    op.drop_index('idx_teaching_space_code', table_name='teaching_space')
    op.drop_column('teaching_space', 'space_code')
