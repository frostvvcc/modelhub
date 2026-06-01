"""remove model_config.vector_db_id

知识库关联职责从 ModelConfig 移至 Bot.vector_db_ids

Revision ID: a1b2c3d4e5f6
Revises: 2024_01_01_0000
Create Date: 2025-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '001_add_org_perm'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index('idx_model_config_vector_db_id', table_name='model_config')
    op.drop_constraint('model_config_ibfk_3', 'model_config', type_='foreignkey')
    op.drop_column('model_config', 'vector_db_id')


def downgrade() -> None:
    op.add_column('model_config', sa.Column('vector_db_id', sa.Integer(), nullable=True))
    op.create_foreign_key('model_config_ibfk_3', 'model_config', 'vector_db', ['vector_db_id'], ['id'])
    op.create_index('idx_model_config_vector_db_id', 'model_config', ['vector_db_id'])
