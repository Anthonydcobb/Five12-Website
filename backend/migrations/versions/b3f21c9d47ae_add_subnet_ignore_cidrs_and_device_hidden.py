"""Add NetworkSubnet.ignore_cidrs and NetworkDevice.hidden

Revision ID: b3f21c9d47ae
Revises: 2114aba7e69a
Create Date: 2026-07-21

Two columns plus the one-time data steps that go with them.

`ignore_cidrs` holds comma-separated ranges inside a subnet that are never
persisted as devices. The venue Wi-Fi /23 is nested in the Management /16 and
its clients are consumer singletons no OUI table can catch, so the subnet
boundary is the only usable filter. Seeded here on the Management subnet, and
the rows it would have prevented are purged once.

`hidden` backs the per-subnet "remove offline devices" button. It is a soft
hide, never a delete, so a device that plugs back in returns with the label and
notes the operator typed on it.

NOTE: apply to MySQL (dev, `five12_website`) AND the desktop SQLite database at
~/Five12Data/five12.db. The desktop app builds its schema with create_all(),
which adds tables but never columns, so an existing SQLite file needs this
migration run against it explicitly.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3f21c9d47ae'
down_revision = '2114aba7e69a'
branch_labels = None
depends_on = None


# The venue Wi-Fi /23 that overlaps Management. [MEASURED 2026-07-21] 145 of
# the 148 unknown devices on Management were inside it.
WIFI_CIDR = '172.16.10.0/23'
MANAGEMENT_CIDR = '172.16.0.0/16'


def upgrade():
    op.add_column('network_subnets',
                  sa.Column('ignore_cidrs', sa.String(length=255),
                            nullable=True))
    op.add_column('network_devices',
                  sa.Column('hidden', sa.Boolean(), nullable=False,
                            server_default='0'))

    conn = op.get_bind()

    # Seed the ignore list on Management. Keyed on the CIDR rather than the
    # label, which is operator-editable free text. Only fills a NULL, so
    # re-running never clobbers a hand-edited list.
    conn.execute(
        sa.text('UPDATE network_subnets SET ignore_cidrs = :wifi '
                'WHERE cidr = :mgmt AND ignore_cidrs IS NULL'),
        {'wifi': WIFI_CIDR, 'mgmt': MANAGEMENT_CIDR},
    )

    # One-time purge of the Wi-Fi rows already in the table. Scoped to rows
    # with NO label and NO notes: a labelled device inside that range would be
    # something the operator deliberately kept, and this must not destroy it.
    conn.execute(
        sa.text("DELETE FROM network_devices "
                "WHERE (last_ip LIKE '172.16.10.%' OR last_ip LIKE '172.16.11.%') "
                "AND (label IS NULL OR label = '') "
                "AND (notes IS NULL OR notes = '')")
    )


def downgrade():
    op.drop_column('network_devices', 'hidden')
    op.drop_column('network_subnets', 'ignore_cidrs')
