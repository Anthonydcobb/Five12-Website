# Active work — SQLite fixture-lock error classification

- **Owner:** Hermes
- **Branch:** `fix/hermes/sqlite-lock-errors`
- **Workspace:** `/root/five12-worktrees/hermes-sqlite-lock-errors`
- **Base SHA:** `6cceb38` (`origin/main`, after reviewed dead-migration cleanup)
- **Status:** complete
- **Last updated:** 2026-07-30

## Goal

Only report a SQLite fixture-catalog operation as busy when SQLite actually reports lock contention. Preserve unrelated `OperationalError` details such as nested transaction misuse instead of returning a misleading 409.

## Acceptance criteria

- [x] `database is locked`, `database table is locked`, and `database schema is locked` map to `FixtureLibraryBusyError`.
- [x] Other SQLite operational errors propagate unchanged.
- [x] Focused fixture-library tests and the full backend suite from `backend/` pass.
- [x] No MySQL, API, schema, migration, or fixture-data changes.

## Reserved paths

- `backend/app/fixture_library.py` (SQLite lock classification only)
- `backend/tests/test_fixture_library.py` (regression tests only)
- `docs/coordination/active/hermes--sqlite-lock-errors.md`

`claude--desktop-schema-bridge.md` still lists `fixture_library.py` but records that task as complete and merged. This follow-up does not touch its removed schema bridge or desktop startup behavior.

## Must-not-touch paths

Models, migrations, frontend, network/BLE/sACN, dependency manifests, database data.

## Evidence

Claude's post-merge Hog review reproduced idle/nested SQLite transaction errors being mislabeled as concurrent fixture operations. Current code catches every `OperationalError` from `BEGIN IMMEDIATE` and maps it to busy.

## Checks

- New non-contention regression was observed failing against `b5ed23b` because it received `FixtureLibraryBusyError`; after the classifier change: **4 passed**.
- `python -m pytest -q tests/test_fixture_library.py` from `backend/` — **25 passed**, 9 warnings.
- `python -m pytest -q tests` from `backend/` — **423 passed**, 19 warnings.
- Canonical root-form suite on this base — **420 passed, 3 failed**, all three pre-existing BLE child-import failures fixed on the separately reviewed preflight-doctor integration branch.
- `git diff --check` — clean.

## Independent review

Exact commit `45289c0` received **Looks Good** with no Critical or Warning findings. The reviewer independently confirmed real SQLAlchemy/SQLite contention maps to 409, unrelated nested-transaction errors reach 500, focused tests passed 25/25, and the diff was clean. The implementation was then rebased without conflict onto current `main` `6cceb38`; the combined canonical suite passed **462 tests** with 19 warnings.

## Handoff / next action

Integrated candidate is ready to fast-forward into `main`. No database migration, catalog import, or live fixture-data write is required.
