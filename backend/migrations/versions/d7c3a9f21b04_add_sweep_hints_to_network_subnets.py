"""add sweep_hints to network_subnets

Comma-separated CIDRs inside a loose subnet that are worth actively sweeping.
`_sweep_targets` reduces a wide CIDR to the /24s holding a local NIC or a
previously-seen device, and on this rig the show gear sits in a /24 with
neither — so nothing ever aimed there and fifteen SideCar nodes stayed
invisible while answering ping in 1ms.

Nullable with no default: a subnet without hints keeps exactly the behaviour it
had before.

Revision ID: d7c3a9f21b04
Revises: c5f1a2b3d4e6
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'd7c3a9f21b04'
down_revision = 'c5f1a2b3d4e6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'network_subnets',
        sa.Column('sweep_hints', sa.String(length=255), nullable=True),
    )


def downgrade():
    op.drop_column('network_subnets', 'sweep_hints')
