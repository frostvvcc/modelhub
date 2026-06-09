"""add token_version to user

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2025-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column(
        'token_version', sa.Integer(),
        nullable=False, server_default='0',
        comment='Token版本号，修改密码时递增，用于使旧JWT立即失效'
    ))


def downgrade():
    op.drop_column('user', 'token_version')
