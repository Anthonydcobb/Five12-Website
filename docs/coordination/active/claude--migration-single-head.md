# Active work — restore a single Alembic head

- **Owner:** Claude
- **Branch:** `fix/claude/migration-single-head`
- **Workspace:** local Windows worktree, `C:\dev\five12-wt\migration-single-head`
- **Base SHA:** `3312a98627ecd6d14f801a2542868cba978c658d` (`origin/main`)
- **Status:** complete — merged to `main` at `2569a4816646be0e7ac1a749fcd07b4ab6ac2143`,
  and applied to the live database
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

## Applied to the live database — 2026-07-30

Anthony authorised the backup and upgrade. Both are done. MySQL 9.7.0, app
stopped (0 listeners on port 5000), `FIVE12_NETWORK_TOOLS=0` and
`FIVE12_BLE_TOOLS=0` so creating the app for the migration started no scanner,
no sACN listener, and no radio.

**Backup, and the part worth reading.** The first `mysqldump` passed every
structural check — 12/12 `CREATE TABLE`, alembic value present, `INSERT`s
present, completion footer — and would not have restored. It carried
`SET @@GLOBAL.GTID_PURGED`, which MySQL refuses to replay onto the server it came
from (`ERROR 3546 (HY000) at line 24`). That was only discovered by restoring it
rather than inspecting it; `mysqldump` had warned about GTIDs and the warning had
been treated as noise. **Any backup step in a plan or runbook needs
`--set-gtid-purged=OFF`** — a structurally perfect dump that cannot be replayed
onto its own server is a false green of exactly the shape this project keeps
finding.

Retaken and proven by restore:

```text
file   : C:\dev\five12-backups\five12_website_2026-07-30_131550_pre-f12hoglib001.sql
size   : 597,643 bytes
sha256 : fabdc8ded1901d30477783fd192be1497f594732616f6eebad8d917bbfeeb318
restore: mysql -u root -p < "<that file>"
```

Proof method: dumped again *without* `--databases` (so the stream carries no
`CREATE DATABASE`/`USE` and cannot redirect itself at the live schema), restored
into a scratch database, compared `CHECKSUM TABLE` for all 12 tables — every
checksum identical — then dropped the scratch database. The unrestorable first
dump was deleted so it cannot be picked up in an emergency.

**Upgrade result.** Exactly one revision ran, `d7c3a9f21b04 -> f12hoglib001`.

| | before | after |
|---|---|---|
| `alembic_version` | `d7c3a9f21b04` | `f12hoglib001` (one row) |
| `fixtures` columns | 7 | 14 |
| `wattage` / `weight` | `NOT NULL` | nullable |
| `fixture_library_backups` | absent | created |
| `network_subnets.sweep_hints` | present | preserved |

Row counts unchanged: fixtures 202, patch_rows 138, patch_sheets 1, shows 1,
network_subnets 4, network_devices 122, label_templates 2. All four new indexes
present.

Verified through the application rather than `information_schema`: created the
app against the live database and read through the ORM — 202 fixtures,
`to_dict()` returning all 17 keys, existing values intact (Skypanel S60 M6 still
420 W / 28 kg), `FixtureLibraryBackup` queryable, `fixture_catalog_checksum()`
computing.

**Still not verified on MySQL:** the downgrade, and the import/restore/lock
behaviour. Hermes' MariaDB 11.4 container run remains the only evidence for
those. The `f12hoglib001` *upgrade* path is now verified on real MySQL data.

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

Merged to `main` and applied to the live database, **without the independent
review README rule 5 calls for** — Anthony directed both the merge and the
upgrade. Flagged here rather than left implicit. Hermes: a post-hoc review of
`2569a481` is still worth having, and the MySQL downgrade is the obvious gap.

`fix/claude/scanner-sweep-interface` can now rebase onto `main` and should drop
nothing — its migration file is already there and byte-identical. That rebase
still carries the unresolved `backend/run_desktop.py` bridge decision (W3 of the
Hog review), which is separate from this change and unaffected by it.
