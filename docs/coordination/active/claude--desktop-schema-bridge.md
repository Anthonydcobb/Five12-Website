# Active work — one desktop SQLite schema bridge

- **Owner:** Claude
- **Branch:** `fix/claude/desktop-schema-bridge`
- **Workspace:** local Windows worktree, `C:\dev\five12-wt\desktop-schema-bridge`
- **Base SHA:** `ad90afd54628832d4e6eda59f6719352ea9ba353` (`origin/main`)
- **Status:** implementation complete, pushed for review
- **Last updated:** 2026-07-30

## Goal

Settle the collision recorded as C2 of the runtime-hardening plan review and W3
of the Hog import review: two different desktop-SQLite schema bridges wired into
the same three lines of `backend/run_desktop.py`.

## The decision

**One generic, metadata-derived bridge. `app/sqlite_schema.py` is it.**

The two implementations were complementary, not duplicate:

- `upgrade_sqlite_schema` (from `fix/claude/scanner-sweep-interface`) is generic
  — it derives additive columns from `db.metadata` and refuses `NOT NULL`
  without a default. It could not relax an existing `NOT NULL`.
- `ensure_desktop_fixture_library_schema` (merged to `main` with the Hog import)
  rebuilt the `fixtures` table specifically to relax `NOT NULL` on
  `wattage`/`weight`, from a hardcoded `CREATE TABLE`.

Neither alone is sufficient, so the generic one gained the missing capability
rather than the specific one being kept alongside it. The rebuild is now derived
from the model via `Table.to_metadata()` + `CreateTable`, which is what closes
W5 of the Hog review: a hand-written `CREATE TABLE` silently drops any column
added to the model after it was written, and it would have, on the next one.

**Relax only, never tighten.** No existing row can violate a weaker constraint,
so relaxing is safe and can be done generically. Tightening can fail on existing
rows and stays a real migration. Pinned by a test.

Also folded in, because a rebuild forces it: model indexes are created on
existing tables. `create_all()` builds a table's indexes only when it builds the
table, and a rebuild drops the old table's indexes with it — so a legacy desktop
database ends up without the four `ix_fixtures_*` indexes either way.

## Changes

- `backend/app/sqlite_schema.py` — brought from the scanner branch
  (byte-identical blob `7c32ba90`), then extended with
  `plan_column_relaxations`, `_rebuild_table`, and `_create_missing_indexes`.
- `backend/app/fixture_library.py` — `ensure_desktop_fixture_library_schema` and
  `_SQLITE_FIXTURE_COLUMNS` deleted; the `inspect` import with them.
- `backend/run_desktop.py` — one call, `upgrade_sqlite_schema(db.engine, db.metadata)`.
- `backend/app/__init__.py` — the same call in `create_app()`'s desktop branch,
  which previously had no bridge at all. That gap was real: a desktop launch
  through `create_app()` would have taken the Hog columns from neither bridge.
- `backend/tests/test_sqlite_schema_upgrade.py` — brought across, decoupled from
  `NetworkSubnet.sweep_hints` (that column is on the scanner branch, not `main`;
  the scenario is kept with a locally declared table), and extended.
- `backend/tests/test_fixture_library.py` — the legacy-desktop test retargeted to
  the unified bridge, now exercising the real startup order (`create_all()` then
  the bridge).

## Reserved paths

- `backend/app/sqlite_schema.py`
- `backend/app/fixture_library.py` (removal of the superseded bridge only)
- `backend/run_desktop.py`
- `backend/app/__init__.py` (desktop schema call only)
- `backend/tests/test_sqlite_schema_upgrade.py`
- `backend/tests/test_fixture_library.py` (the legacy-desktop test only)
- `docs/coordination/active/claude--desktop-schema-bridge.md`

## Must-not-touch paths

Migrations, models, dependency manifests, `.env`, network/BLE paths, frontend.

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| `pytest -q tests` from `backend/`, app interpreter | **419 passed**, 118 warnings, 15.58 s | software verification (Windows rig) |
| `pytest -q tests/test_sqlite_schema_upgrade.py` | **15 passed** | software verification (Windows rig) |
| `pytest -q tests/test_fixture_library.py -k legacy` | **1 passed** | software verification (Windows rig) |

Written test-first. The relaxation test and the index test were each watched
failing for the right reason before the code existed — the relaxation test
failed on `wattage` still being `NOT NULL` *after* the additive pass had
correctly added all seven Hog columns, which is precisely the gap. The five
tests that follow them (row survival, obsolete-column drop, model queryable,
idempotency, never-tighten) passed on first run: they characterise and pin
behaviour the rebuild already had, and are recorded as such rather than
presented as driven.

**Not verified:** desktop mode has not been launched. No `run_desktop.py` start,
no Electron. The startup sequence is exercised by the retargeted test rather
than by running the application.

## Correction to a previously published finding

W2 of `2026-07-30--claude-review-of-runtime-hardening-plan.md` stated that
`test_ble_scanner.py`'s five lock tests fail "because the Five12 backend was
running ... and holds the machine-wide Bluetooth lock." The second half is
right, the precondition is not: during this task the backend was running and all
18 lock tests passed, because that instance had **BLE tools off** — the
`/api/ble/capabilities` route was absent, so it never took the adapter lock.

The correct precondition is *a process holding the BLE adapter lock*, which
means the app running **with `FIVE12_BLE_TOOLS=1`**, not the app running. W2's
substance is unchanged and arguably strengthened: the baseline in plan Task 0.2
is not reproducible unless the precondition is stated, and the state that
determines the outcome is invisible both in the failure message and from
looking at whether the app is up. The review has been amended.

## Handoff / next action

Hermes: review. The judgement worth a second opinion is the generic
relax-never-tighten rule — a metadata-derived rebuild is more powerful than
either original bridge, and the argument that relaxing is always safe is the
load-bearing one.

After this merges, `fix/claude/scanner-sweep-interface` rebases and drops its
copies of `app/sqlite_schema.py` and `backend/tests/test_sqlite_schema_upgrade.py`
— both are here, the module byte-identical at its base plus the extensions. That
was the last thing blocking that rebase.
