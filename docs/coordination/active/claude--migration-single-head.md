# Active work — restore a single Alembic head

- **Owner:** Claude
- **Branch:** `fix/claude/migration-single-head`
- **Workspace:** local Windows worktree, `C:\dev\five12-wt\migration-single-head`
- **Base SHA:** `3312a98627ecd6d14f801a2542868cba978c658d` (`origin/main`)
- **Status:** implementation complete, pushed for review
- **Last updated:** 2026-07-30

## Goal

Make `flask db upgrade` work again against the live database. `f12hoglib001`
(Hog fixture library, on `main`) and `d7c3a9f21b04` (scanner sweep hints, on
`fix/claude/scanner-sweep-interface`) were both authored with
`down_revision = c5f1a2b3d4e6` on separate branches, giving the graph two heads.
Reported as C1 in `docs/coordination/reviews/2026-07-30--claude-review-of-hog-fixture-import.md`.

## The constraint that decided the direction

The live database is stamped `d7c3a9f21b04`; `f12hoglib001` has not been applied
anywhere but disposable test databases. So the chain can only be linearized one
way. Re-parenting `d7c3a9f21b04` onto `f12hoglib001` would have made Alembic
treat `f12hoglib001` as an already-applied ancestor of the live rig's current
revision, so the Hog columns and `fixture_library_backups` would never have been
created and the first query against `fixtures.manufacturer` would have failed.

`d7c3a9f21b04` therefore keeps its position and `f12hoglib001` moves behind it.
The two touch disjoint tables — `fixtures` / `fixture_library_backups` versus
`network_subnets` — so the order carries no semantic weight.

## Changes

- `backend/migrations/versions/f12hoglib001_add_hog_fixture_library.py` —
  `down_revision` `c5f1a2b3d4e6` → `d7c3a9f21b04`, with the reason in the
  docstring.
- `backend/migrations/versions/d7c3a9f21b04_add_sweep_hints_to_network_subnets.py`
  — brought onto `main` unchanged from `fix/claude/scanner-sweep-interface`.
  Byte-identical blob (`6ad7aadd`), so that branch's rebase sees no conflict.
  `main` was missing a migration that is already applied to the live database;
  that gap is what left the rig unreachable from `main`'s chain.

## Reserved paths

- `backend/migrations/versions/f12hoglib001_add_hog_fixture_library.py`
- `backend/migrations/versions/d7c3a9f21b04_add_sweep_hints_to_network_subnets.py`
- `docs/coordination/active/claude--migration-single-head.md`

## Must-not-touch paths

Everything else. No application code, model, dependency, or configuration change.

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| Alembic `ScriptDirectory.get_heads()` | **1 head**, `f12hoglib001`; chain linear to base | software verification (Windows rig) |
| Scenario A — fresh SQLite, base → head | version `f12hoglib001`, all three schema markers present | software verification (Windows rig) |
| Scenario B — SQLite stamped `d7c3a9f21b04`, then `upgrade` | applied exactly `f12hoglib001`; `sweep_hints` preserved | software verification (Windows rig) |
| Scenario C — downgrade to `c5f1a2b3d4e6`, then re-upgrade | clean both directions | software verification (Windows rig) |
| `python -m pytest -q tests` from `backend/`, app interpreter | 5 failed, 399 passed | software verification (Windows rig) |
| `pytest tests/test_fixture_library.py -k "alembic or downgrade or legacy"` | **2 passed** | software verification (Windows rig) |

Scenario B is the one that matters: it reproduces the live rig's exact starting
state and proves a single revision is applied on top of it.

The 5 suite failures are `test_ble_scanner.py`'s adapter-lock tests, failing
because the Five12 backend was running (PID 37264 owning port 5000) and holds
the machine-wide Bluetooth lock. Unrelated to this change — with the app stopped
the same suite reports 404 passed on this branch's parent. This is finding W2 of
the runtime-hardening plan review, observed for the third time today.

**Not verified:** MySQL. All four migration scenarios ran on SQLite. The live
database is MySQL, and `f12hoglib001` uses `batch_alter_table`, which behaves
differently there. Anthony should back up before upgrading, and the MySQL path
is the obvious target for independent verification.

## Risks

- Any database that already applied `f12hoglib001` under the old parent — that
  is, Hermes' disposable test databases — now has an `alembic_version` that
  implies `d7c3a9f21b04` was applied when it was not. Recreate those rather than
  upgrading them. No production database is affected, because `f12hoglib001` was
  never applied to one.
- `main` now contains the sweep-hints migration without the scanner code that
  reads the column. The column is nullable with no default, so behaviour is
  unchanged until that branch lands; and this exactly matches the live database's
  existing state.

## Handoff / next action

Hermes: review and integrate. After this merges,
`fix/claude/scanner-sweep-interface` rebases onto `main` and should drop nothing
— its migration file is already there and identical. That rebase still carries
the unresolved `backend/run_desktop.py` bridge decision (W3 of the Hog review),
which is separate from this change.

Anthony: do not run `flask db upgrade` against the real database until this is
merged, and back it up first.
