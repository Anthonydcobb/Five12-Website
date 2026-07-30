"""add Hog fixture metadata and restorable catalog backups

Revision ID: f12hoglib001
Revises: d7c3a9f21b04
Create Date: 2026-07-29

Re-parented from c5f1a2b3d4e6 to d7c3a9f21b04 on 2026-07-30. Both revisions
were authored against c5f1a2b3d4e6 on separate branches, so the graph had two
heads and `flask db upgrade` had nothing to aim at. d7c3a9f21b04 is the one
already applied to the live database, so it keeps its position and this one
moves behind it. The two touch disjoint tables — fixtures and
fixture_library_backups here, network_subnets there — so the order is free.
"""

from alembic import op
import sqlalchemy as sa


revision = "f12hoglib001"
down_revision = "d7c3a9f21b04"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("fixtures") as batch_op:
        batch_op.alter_column("wattage", existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column("weight", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column("manufacturer", sa.String(120), nullable=True))
        batch_op.add_column(sa.Column("hog_uuid", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("revision_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("library_type", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("library_origin", sa.String(120), nullable=True))
        batch_op.add_column(sa.Column("library_source", sa.String(50), nullable=True))
        batch_op.add_column(sa.Column("library_version", sa.String(32), nullable=True))
        batch_op.create_index("ix_fixtures_manufacturer", ["manufacturer"])
        batch_op.create_index("ix_fixtures_hog_uuid", ["hog_uuid"])
        batch_op.create_index("ix_fixtures_library_source", ["library_source"])
        batch_op.create_index("ix_fixtures_library_version", ["library_version"])

    op.create_table(
        "fixture_library_backups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("fixture_count", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("version", sa.String(32), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("fixtures_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("fixture_library_backups")
    # The legacy schema cannot represent unknown values. A downgrade is
    # therefore intentionally lossy for imported Hog rows, but remains
    # executable instead of failing on their NULL wattage/weight fields.
    op.execute("UPDATE fixtures SET wattage = 0 WHERE wattage IS NULL")
    op.execute("UPDATE fixtures SET weight = 0 WHERE weight IS NULL")
    with op.batch_alter_table("fixtures") as batch_op:
        batch_op.drop_index("ix_fixtures_library_version")
        batch_op.drop_index("ix_fixtures_library_source")
        batch_op.drop_index("ix_fixtures_hog_uuid")
        batch_op.drop_index("ix_fixtures_manufacturer")
        batch_op.drop_column("library_version")
        batch_op.drop_column("library_source")
        batch_op.drop_column("library_origin")
        batch_op.drop_column("library_type")
        batch_op.drop_column("revision_id")
        batch_op.drop_column("hog_uuid")
        batch_op.drop_column("manufacturer")
        batch_op.alter_column("weight", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("wattage", existing_type=sa.Integer(), nullable=False)
