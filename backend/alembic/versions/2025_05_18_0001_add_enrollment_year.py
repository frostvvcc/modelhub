"""add enrollment_year to user and teaching_space_major

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2025-05-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    # user 表添加 enrollment_year 列
    op.add_column('user', sa.Column('enrollment_year', sa.Integer(), nullable=True, comment='入学年份，由学号前4位自动识别'))
    op.create_index('idx_user_enrollment_year', 'user', ['enrollment_year'])

    # teaching_space_major 表添加 enrollment_year 列
    op.add_column('teaching_space_major', sa.Column('enrollment_year', sa.Integer(), nullable=True, comment='绑定的年级（入学年份），NULL表示该专业全部年级'))
    op.create_index('idx_ts_major_enrollment_year', 'teaching_space_major', ['enrollment_year'])

    # 更新唯一约束：从 (space_id, major_id) 改为 (space_id, major_id, enrollment_year)
    op.drop_constraint('uq_space_major', 'teaching_space_major', type_='unique')
    op.create_unique_constraint('uq_space_major_year', 'teaching_space_major', ['space_id', 'major_id', 'enrollment_year'])

    # 数据迁移：已有学生如果有 student_id，自动从前4位提取 enrollment_year
    op.execute("""
        UPDATE user
        SET enrollment_year = CAST(SUBSTRING(student_id, 1, 4) AS UNSIGNED)
        WHERE student_id IS NOT NULL
          AND LENGTH(student_id) >= 4
          AND SUBSTRING(student_id, 1, 4) REGEXP '^[0-9]{4}$'
          AND CAST(SUBSTRING(student_id, 1, 4) AS UNSIGNED) BETWEEN 2000 AND 2099
          AND role = 'student'
    """)


def downgrade():
    op.drop_constraint('uq_space_major_year', 'teaching_space_major', type_='unique')
    op.create_unique_constraint('uq_space_major', 'teaching_space_major', ['space_id', 'major_id'])
    op.drop_index('idx_ts_major_enrollment_year', table_name='teaching_space_major')
    op.drop_column('teaching_space_major', 'enrollment_year')
    op.drop_index('idx_user_enrollment_year', table_name='user')
    op.drop_column('user', 'enrollment_year')
