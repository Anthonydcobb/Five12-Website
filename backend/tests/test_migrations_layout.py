"""There is one Alembic history, and it lives in backend/migrations/.

There used to be two. A dead copy at the repository root shadowed the real one,
and which chain you got depended on the directory you happened to run
`flask db` from — Flask-Migrate resolves its directory relative to the working
directory, so from the repo root you silently drove the dead chain.

It cost this project a day, and later a confidently wrong diagnosis: an agent
following `AGENTS.md`, which said the schema was "managed via
Flask-Migrate/Alembic in `migrations/`", read the dead copy, concluded the
migration chain was broken beyond use, and published that conclusion before
catching it. Nothing was broken except which folder was being read.

These tests are the cheap guard against it coming back. They read the
filesystem, touch no database, and run anywhere.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERSIONS = REPO / 'backend' / 'migrations' / 'versions'

REVISION_RE = re.compile(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", re.M)
DOWN_RE = re.compile(r"^down_revision\s*=\s*(?:['\"]([^'\"]+)['\"]|None)", re.M)


def _migrations():
    out = []
    for path in sorted(VERSIONS.glob('*.py')):
        text = path.read_text(encoding='utf-8')
        revision = REVISION_RE.search(text)
        down = DOWN_RE.search(text)
        assert revision, f'{path.name} declares no revision'
        assert down, f'{path.name} declares no down_revision'
        out.append((path.name, revision.group(1), down.group(1)))
    return out


def test_there_is_no_second_migrations_directory():
    """The whole point. `flask db init` from the repo root would recreate it."""
    assert not (REPO / 'migrations').exists(), (
        'a root-level migrations/ directory is back. There must be exactly one '
        'Alembic history, at backend/migrations/ — two chains means the one you '
        'get depends on your working directory.'
    )


def test_the_real_migrations_directory_is_where_we_say_it_is():
    assert VERSIONS.is_dir(), f'no migrations at {VERSIONS}'
    assert list(VERSIONS.glob('*.py')), 'the migrations directory is empty'


def test_the_docs_point_at_the_real_directory():
    """AGENTS.md sent an agent to the dead copy once already.

    Checking merely that `backend/migrations` appears somewhere is not enough:
    both files already contained that phrase in their repository-layout section
    while the database paragraph still said `migrations/`. A test that passes
    while the misleading sentence is present guards nothing. So this asserts
    the schema-management sentence itself names the real directory, and that
    the ambiguous unqualified form is absent.
    """
    ambiguous = re.compile(r'Alembic in `migrations/`')
    schema_sentence = re.compile(
        r'Schema managed via [^\n]*`backend/migrations/`'
    )
    for name in ('AGENTS.md', 'CLAUDE.md'):
        text = (REPO / name).read_text(encoding='utf-8')
        assert not ambiguous.search(text), (
            f'{name} still says "Alembic in `migrations/`" — that is the dead '
            'copy, and it is what sent an agent to the wrong directory'
        )
        assert schema_sentence.search(text), (
            f'{name}: the schema-management sentence must name '
            '`backend/migrations/` explicitly, not just mention it elsewhere'
        )
        assert 'from `backend/`' in text, (
            f'{name} must say to run flask db commands from `backend/` — the '
            'directory is resolved relative to the working directory'
        )


def test_revision_ids_are_unique():
    revisions = [rev for _, rev, _ in _migrations()]
    duplicates = {r for r in revisions if revisions.count(r) > 1}
    assert not duplicates, f'duplicate revision ids: {sorted(duplicates)}'


def test_every_down_revision_exists():
    migrations = _migrations()
    known = {rev for _, rev, _ in migrations}
    dangling = [
        (name, down) for name, _, down in migrations
        if down is not None and down not in known
    ]
    assert not dangling, f'down_revision points at a missing revision: {dangling}'


def test_exactly_one_base_and_one_head():
    """Two heads means `flask db upgrade` stops and asks which you meant, which
    in practice means it does not run."""
    migrations = _migrations()
    referenced = {down for _, _, down in migrations if down is not None}
    heads = [rev for _, rev, _ in migrations if rev not in referenced]
    bases = [rev for _, rev, down in migrations if down is None]

    assert len(bases) == 1, f'expected one base migration, found {bases}'
    assert len(heads) == 1, f'expected one head, found {heads}'
