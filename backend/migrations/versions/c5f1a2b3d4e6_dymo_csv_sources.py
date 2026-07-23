"""dymo csv sources

Revision ID: c5f1a2b3d4e6
Revises: e85115f40999
Create Date: 2026-07-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c5f1a2b3d4e6'
down_revision = 'e85115f40999'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('dymo_csv_sources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('headers', sa.JSON(), nullable=False),
    sa.Column('rows', sa.JSON(), nullable=False),
    sa.Column('row_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('dymo_csv_sources')
