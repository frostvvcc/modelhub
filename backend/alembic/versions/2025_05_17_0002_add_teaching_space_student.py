"""add teaching_space_student table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2025-05-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'teaching_space_student',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('space_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['space_id'], ['teaching_space.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('space_id', 'student_id', name='uq_space_student'),
    )
    op.create_index('idx_ts_student_space_id', 'teaching_space_student', ['space_id'])
    op.create_index('idx_ts_student_student_id', 'teaching_space_student', ['student_id'])


def downgrade():
    op.drop_index('idx_ts_student_student_id', table_name='teaching_space_student')
    op.drop_index('idx_ts_student_space_id', table_name='teaching_space_student')
    op.drop_table('teaching_space_student')
