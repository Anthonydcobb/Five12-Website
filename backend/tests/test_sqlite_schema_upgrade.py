"""An existing desktop database must survive a new column.

Reproduces the regression found in review of the sweep-hints branch. Desktop
mode builds its schema with `db.create_all()`, which creates missing tables and
never alters an existing one — so `network_subnets.sweep_hints` was absent from
any database created before that column existed, and the first query against
the model died:

    sqlite3.OperationalError: no such column: network_subnets.sweep_hints

The fix is deliberately narrow: additive, nullable-only, SQLite-only. These
tests pin both halves — that it adds what is safe, and that it refuses what is
not.
"""

import sqlalchemy as sa

from app.models import NetworkSubnet
from app.sqlite_schema import (
    plan_additive_columns,
    plan_column_relaxations,
    upgrade_sqlite_schema,
)


# The pre-branch shape of the table: everything except sweep_hints.
_OLD_SCHEMA = """
CREATE TABLE network_subnets (
    id INTEGER NOT NULL PRIMARY KEY,
    label VARCHAR(100) NOT NULL,
    cidr VARCHAR(50) NOT NULL,
    interface_hint VARCHAR(50),
    color VARCHAR(20) NOT NULL,
    active BOOLEAN NOT NULL,
    ignore_cidrs VARCHAR(255),
    created_at DATETIME
)
"""


def _old_desktop_database(tmp_path, db):
    """A SQLite file shaped like a desktop database from before the column,
    with a row in it."""
    path = tmp_path / "five12-old.sqlite3"
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(sa.text(_OLD_SCHEMA))
        conn.execute(sa.text(
            "INSERT INTO network_subnets "
            "(id, label, cidr, interface_hint, color, active, ignore_cidrs) "
            "VALUES (1, 'sACN', '10.0.0.0/8', NULL, '#7dd3fc', 1, NULL)"
        ))
    return engine


def test_an_old_desktop_database_is_missing_the_column(tmp_path, db):
    """Guard the premise: if this ever stops being true the rest is theatre."""
    engine = _old_desktop_database(tmp_path, db)
    columns = {c["name"] for c in sa.inspect(engine).get_columns("network_subnets")}
    assert "sweep_hints" not in columns


def _model_with_sweep_hints():
    """The sweep-hints shape of `network_subnets`, declared locally.

    The column itself lives on `fix/claude/scanner-sweep-interface` and is not
    on `main`, but the regression it caused is the reason this module exists, so
    the scenario is kept and the dependency on that branch's model is not. This
    module is generic; its tests should not need one feature branch's column.
    """
    metadata = sa.MetaData()
    sa.Table(
        "network_subnets", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("cidr", sa.String(50), nullable=False),
        sa.Column("interface_hint", sa.String(50)),
        sa.Column("color", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("ignore_cidrs", sa.String(255)),
        sa.Column("created_at", sa.DateTime),
        sa.Column("sweep_hints", sa.String(255)),
    )
    return metadata


def test_the_upgrade_adds_the_column_and_keeps_the_existing_row(tmp_path, db):
    engine = _old_desktop_database(tmp_path, db)

    added = upgrade_sqlite_schema(engine, _model_with_sweep_hints())

    assert ("network_subnets", "sweep_hints") in added
    columns = {c["name"] for c in sa.inspect(engine).get_columns("network_subnets")}
    assert "sweep_hints" in columns

    with engine.connect() as conn:
        rows = conn.execute(sa.text(
            "SELECT label, cidr, sweep_hints FROM network_subnets"
        )).fetchall()
    assert rows == [("sACN", "10.0.0.0/8", None)], "the existing row must survive"


def test_selecting_the_new_column_works_after_the_upgrade(tmp_path, db):
    """The actual failure mode: SELECT names every mapped column, so a missing
    one takes the whole query down."""
    engine = _old_desktop_database(tmp_path, db)

    with engine.connect() as conn:
        try:
            conn.execute(sa.text("SELECT sweep_hints FROM network_subnets"))
            column_was_present = True
        except sa.exc.OperationalError:
            column_was_present = False
    assert column_was_present is False, "premise: the column is absent before upgrade"

    upgrade_sqlite_schema(engine, _model_with_sweep_hints())

    with engine.connect() as conn:
        rows = conn.execute(sa.text(
            "SELECT label, sweep_hints FROM network_subnets"
        )).fetchall()
    assert rows == [("sACN", None)]


def test_the_upgrade_is_a_no_op_when_nothing_is_missing(tmp_path, db):
    engine = _old_desktop_database(tmp_path, db)
    upgrade_sqlite_schema(engine, _model_with_sweep_hints())
    assert upgrade_sqlite_schema(engine, _model_with_sweep_hints()) == []


def test_it_refuses_a_not_null_column_without_a_default(tmp_path, db):
    """There is no correct value for the existing rows, so it is reported and
    skipped rather than guessed at."""
    engine = _old_desktop_database(tmp_path, db)

    metadata = sa.MetaData()
    sa.Table(
        "network_subnets", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("cidr", sa.String(50), nullable=False),
        sa.Column("must_be_set", sa.String(10), nullable=False),
    )

    to_add, unsafe = plan_additive_columns(engine, metadata)

    assert to_add == []
    assert [(t, c) for t, c, _reason in unsafe] == [("network_subnets", "must_be_set")]
    assert upgrade_sqlite_schema(engine, metadata) == []


def test_it_leaves_a_missing_table_to_create_all(tmp_path, db):
    engine = _old_desktop_database(tmp_path, db)

    metadata = sa.MetaData()
    sa.Table(
        "some_new_table", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )

    to_add, unsafe = plan_additive_columns(engine, metadata)
    assert (to_add, unsafe) == ([], [])


def test_it_refuses_to_touch_a_non_sqlite_engine(db):
    """MySQL's schema belongs to Alembic. This must not step on it."""

    class _FakeDialect:
        name = "mysql"

    class _FakeEngine:
        dialect = _FakeDialect()

    assert upgrade_sqlite_schema(_FakeEngine(), NetworkSubnet.metadata) == []


# ── Relaxing NOT NULL ─────────────────────────────────────────────────────────
#
# The second half of the desktop problem, found when the Hog fixture-library
# import landed its own private bridge doing the same job. Adding a column is
# only one kind of drift: `fixtures.wattage` and `fixtures.weight` were NOT NULL
# and the model now says nullable, because an imported vendor profile genuinely
# does not know a fixture's power draw. SQLite cannot alter a column in place,
# so the table has to be rebuilt.
#
# Relaxing is safe and generic — no existing row can violate a weaker
# constraint. Tightening is not, and must never happen here.

_LEGACY_FIXTURES = """
CREATE TABLE fixtures (
    id INTEGER PRIMARY KEY,
    fixture VARCHAR(120) NOT NULL,
    mode VARCHAR(120),
    channel_count INTEGER NOT NULL,
    wattage INTEGER NOT NULL,
    weight INTEGER NOT NULL,
    firmware VARCHAR(120),
    notes TEXT
)
"""


def _legacy_fixture_database(tmp_path):
    """A desktop database from before the Hog import: wattage/weight NOT NULL,
    none of the library columns, and an obsolete `mode` column."""
    path = tmp_path / "five12-legacy-fixtures.sqlite3"
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(sa.text(_LEGACY_FIXTURES))
        conn.execute(sa.text(
            "INSERT INTO fixtures "
            "(id, fixture, mode, channel_count, wattage, weight, firmware, notes) "
            "VALUES (1, 'Legacy Fixture', 'Legacy Mode', 7, 125, 9, '1.2.3', 'keep')"
        ))
    return engine


def _nullability(engine, table):
    return {row[1]: row[3] == 0 for row in engine.connect().execute(
        sa.text(f"PRAGMA table_info({table})"))}


def test_legacy_fixture_columns_start_not_null(tmp_path, db):
    """Guard the premise."""
    engine = _legacy_fixture_database(tmp_path)
    nullable = _nullability(engine, "fixtures")
    assert nullable["wattage"] is False
    assert nullable["weight"] is False


def test_the_upgrade_relaxes_not_null_to_match_the_model(tmp_path, db):
    from app.models import Fixture

    engine = _legacy_fixture_database(tmp_path)

    upgrade_sqlite_schema(engine, Fixture.metadata)

    nullable = _nullability(engine, "fixtures")
    assert nullable["wattage"] is True, "the model says nullable; the table must agree"
    assert nullable["weight"] is True


def _index_names(engine, table):
    return {row[1] for row in engine.connect().execute(
        sa.text(f"PRAGMA index_list({table})"))}


def test_the_upgrade_creates_indexes_the_legacy_table_never_had(tmp_path, db):
    """`create_all()` builds indexes only when it builds the table, and a
    rebuild drops them along with the old table. Either way a legacy database
    ends up without the model's indexes unless they are created explicitly."""
    from app.models import Fixture

    engine = _legacy_fixture_database(tmp_path)
    assert _index_names(engine, "fixtures") == set(), "premise: no indexes yet"

    upgrade_sqlite_schema(engine, Fixture.metadata)

    expected = {index.name for index in Fixture.__table__.indexes}
    assert expected, "premise: the model declares indexes"
    assert expected.issubset(_index_names(engine, "fixtures"))


def test_the_rebuild_keeps_every_row_and_value(tmp_path, db):
    """A rebuild moves the data. If it loses a value it is worse than the bug."""
    from app.models import Fixture

    engine = _legacy_fixture_database(tmp_path)

    upgrade_sqlite_schema(engine, Fixture.metadata)

    with engine.connect() as conn:
        rows = conn.execute(sa.text(
            "SELECT id, fixture, channel_count, wattage, weight, firmware, notes "
            "FROM fixtures"
        )).fetchall()
    assert rows == [(1, "Legacy Fixture", 7, 125, 9, "1.2.3", "keep")]


def test_the_rebuild_drops_a_column_the_model_no_longer_has(tmp_path, db):
    """`mode` was removed from the model by an earlier migration. A rebuilt
    table is what create_all() would have made, which does not include it."""
    from app.models import Fixture

    engine = _legacy_fixture_database(tmp_path)
    assert "mode" in {c["name"] for c in sa.inspect(engine).get_columns("fixtures")}

    upgrade_sqlite_schema(engine, Fixture.metadata)

    assert "mode" not in {c["name"] for c in sa.inspect(engine).get_columns("fixtures")}


def test_the_model_is_queryable_after_the_rebuild(tmp_path, db):
    from app.models import Fixture

    engine = _legacy_fixture_database(tmp_path)
    upgrade_sqlite_schema(engine, Fixture.metadata)

    Session = sa.orm.sessionmaker(bind=engine)
    with Session() as session:
        fixture = session.query(Fixture).one()
        assert fixture.fixture == "Legacy Fixture"
        assert fixture.wattage == 125
        assert fixture.manufacturer is None
        assert fixture.to_dict()["libraryVersion"] is None


def test_running_it_twice_rebuilds_only_once(tmp_path, db):
    from app.models import Fixture

    engine = _legacy_fixture_database(tmp_path)
    upgrade_sqlite_schema(engine, Fixture.metadata)

    assert plan_column_relaxations(engine, Fixture.metadata) == []
    assert upgrade_sqlite_schema(engine, Fixture.metadata) == []


def test_it_never_tightens_a_nullable_column(tmp_path, db):
    """The dangerous direction. An existing NULL would violate the new
    constraint, so a model that tightens needs a real migration, not this."""
    engine = _legacy_fixture_database(tmp_path)

    metadata = sa.MetaData()
    sa.Table(
        "fixtures", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fixture", sa.String(120), nullable=False),
        sa.Column("channel_count", sa.Integer, nullable=False),
        sa.Column("wattage", sa.Integer, nullable=False),
        sa.Column("weight", sa.Integer, nullable=False),
        # nullable in the legacy table, NOT NULL in this model: a tightening
        sa.Column("firmware", sa.String(120), nullable=False),
        sa.Column("notes", sa.Text),
    )

    assert plan_column_relaxations(engine, metadata) == []

    upgrade_sqlite_schema(engine, metadata)

    nullable = _nullability(engine, "fixtures")
    assert nullable["firmware"] is True, "firmware must stay nullable"
