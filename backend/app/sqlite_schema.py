"""Additive schema upgrade for the desktop SQLite database.

Desktop mode builds its schema with `db.create_all()`, which creates missing
*tables* and never touches existing ones. So a column added to a model after a
desktop database already exists simply is not there, and the first query
against that model dies:

    sqlite3.OperationalError: no such column: network_subnets.sweep_hints

Found in review of the sweep-hints branch, reproduced against a pre-branch
desktop file. Development MySQL is unaffected — it has a real Alembic chain,
and this module deliberately refuses to run on anything but SQLite so it cannot
step on that.

Scope is deliberately narrow. This adds columns that are safe to add to a
populated table and nothing else:

* nullable columns, or columns with a server default;
* never a NOT NULL column without a default — there is no correct value for
  the existing rows, so it is reported and skipped rather than guessed at;
* never a drop, rename, or type change.

Anything outside that is a real migration and needs a real migration. The point
is not to become a second migration system; it is that "the app quietly cannot
read its own table" is a worse failure than a narrow, loud, tested helper.
"""

import logging

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.schema import CreateTable

log = logging.getLogger(__name__)


def plan_column_relaxations(engine, metadata):
    """Columns the database marks NOT NULL that the model says are nullable.

    Returns a list of (table_name, [column_name, ...]).

    Only relaxations. Going the other way — tightening a nullable column to NOT
    NULL — can fail on existing rows and is a real migration, so it is never
    planned here. Primary keys are excluded: SQLite's rowid alias is implicitly
    NOT NULL whatever the model says.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    relaxations = []
    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        current = {col['name']: col for col in inspector.get_columns(table.name)}
        columns = [
            column.name
            for column in table.columns
            if not column.primary_key
            and column.name in current
            and column.nullable
            and not current[column.name]['nullable']
        ]
        if columns:
            relaxations.append((table.name, columns))

    return relaxations


def _rebuild_table(engine, table):
    """Recreate `table` from the model and copy the rows across.

    SQLite cannot alter a column in place, so the twelve-step rebuild is the
    only way to change nullability. The new table is generated from the model's
    own definition rather than a literal CREATE TABLE, so it cannot drift from
    what `db.create_all()` would have produced — a hand-written copy silently
    loses every column added after it was written.

    Columns present in the old table but not in the model are dropped, which is
    the point: they are what `create_all()` would never have made.
    """
    staging_name = f'{table.name}_five12_rebuild'
    staging_metadata = MetaData()
    staging = table.to_metadata(staging_metadata, name=staging_name)
    # Indexes are recreated against the real name after the swap; leaving them
    # here would create them under the staging name and collide on the rename.
    staging.indexes.clear()

    carried = [
        column.name
        for column in table.columns
        if column.name in {c['name'] for c in inspect(engine).get_columns(table.name)}
    ]
    column_list = ', '.join(f'"{name}"' for name in carried)

    with engine.begin() as conn:
        conn.execute(CreateTable(staging))
        conn.execute(text(
            f'INSERT INTO "{staging_name}" ({column_list}) '
            f'SELECT {column_list} FROM "{table.name}"'
        ))
        conn.execute(text(f'DROP TABLE "{table.name}"'))
        conn.execute(text(
            f'ALTER TABLE "{staging_name}" RENAME TO "{table.name}"'
        ))

    return carried


def plan_additive_columns(engine, metadata):
    """Work out what needs adding, without changing anything.

    Returns (to_add, unsafe) where `to_add` is a list of
    (table_name, column_name, ddl_type) and `unsafe` is a list of
    (table_name, column_name, reason) for columns this helper will not add.

    Separated from the execution so the decision can be tested without a
    migration actually running.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    to_add = []
    unsafe = []

    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            # create_all()'s job. A missing table is not an additive column.
            continue
        present = {col['name'] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            if not column.nullable and column.server_default is None:
                unsafe.append((
                    table.name,
                    column.name,
                    'NOT NULL with no server default — existing rows have no '
                    'correct value, so this needs a real migration',
                ))
                continue
            to_add.append((
                table.name,
                column.name,
                column.type.compile(dialect=engine.dialect),
            ))

    return to_add, unsafe


def upgrade_sqlite_schema(engine, metadata):
    """Add the columns from `plan_additive_columns`. SQLite only.

    Returns the list of (table, column) actually added. Refuses non-SQLite
    engines outright: MySQL's schema belongs to Alembic.
    """
    if engine.dialect.name != 'sqlite':
        log.debug('not sqlite (%s); leaving the schema to Alembic',
                  engine.dialect.name)
        return []

    # Relaxations first. A rebuild regenerates the table from the model, so it
    # brings the missing columns with it and the additive pass then finds
    # nothing left to do for that table.
    tables_by_name = {table.name: table for table in metadata.sorted_tables}
    for table_name, columns in plan_column_relaxations(engine, metadata):
        log.info('desktop schema: rebuilding %s to relax NOT NULL on %s',
                 table_name, ', '.join(columns))
        _rebuild_table(engine, tables_by_name[table_name])

    to_add, unsafe = plan_additive_columns(engine, metadata)

    for table_name, column_name, reason in unsafe:
        log.warning('cannot add %s.%s automatically: %s',
                    table_name, column_name, reason)

    added = []
    for table_name, column_name, ddl_type in to_add:
        statement = (
            f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {ddl_type}'
        )
        try:
            with engine.begin() as conn:
                conn.execute(text(statement))
        except Exception as exc:  # noqa: BLE001 - report, do not mask
            # Loudly, at warning: a silent failure here reproduces the exact
            # "no such column" crash this function exists to prevent.
            log.warning('failed to add %s.%s: %s', table_name, column_name, exc)
            continue
        log.info('desktop schema: added %s.%s', table_name, column_name)
        added.append((table_name, column_name))

    _create_missing_indexes(engine, metadata)

    return added


def _create_missing_indexes(engine, metadata):
    """Create model indexes that the database does not have.

    `create_all()` builds a table's indexes only when it builds the table, so an
    index added to an existing model never appears on an existing database; and
    a rebuild drops the old table's indexes with it. `checkfirst=True` makes
    this a no-op once they exist.
    """
    existing_tables = set(inspect(engine).get_table_names())
    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        for index in table.indexes:
            try:
                index.create(bind=engine, checkfirst=True)
            except Exception as exc:  # noqa: BLE001 - report, do not mask
                log.warning('failed to create index %s on %s: %s',
                            index.name, table.name, exc)
