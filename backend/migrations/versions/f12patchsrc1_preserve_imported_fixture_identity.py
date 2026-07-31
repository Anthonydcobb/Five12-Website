"""preserve imported patch fixture identity

Revision ID: f12patchsrc1
Revises: f12hoglib001
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa


revision = 'f12patchsrc1'
down_revision = 'f12hoglib001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('patch_rows') as batch_op:
        batch_op.add_column(sa.Column(
            'imported_fixture_type', sa.Text(), nullable=True
        ))
        batch_op.add_column(sa.Column(
            'imported_channel_count', sa.Integer(), nullable=True
        ))


def downgrade():
    with op.batch_alter_table('patch_rows') as batch_op:
        batch_op.drop_column('imported_channel_count')
        batch_op.drop_column('imported_fixture_type')
