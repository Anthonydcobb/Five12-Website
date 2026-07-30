# Review — Hog fixture-library import

- **Date:** 2026-07-30
- **Reviewer:** Claude Code (local Windows session, `C:\dev\Five12-TheApp`)
- **Implementation branch:** `feat/hermes/hog-fixture-import`
- **Reviewed commit (pinned):** `3312a98627ecd6d14f801a2542868cba978c658d`
- **Scope:** backend import/lock/restore paths, model and migration changes, route
  changes, and the frontend surfaces that consume them.

## Status change during this review

`origin/main` moved while this review was in progress. At the start of my session
it was `aa4b25b9d2411ec9565ebcb918b3e302f9883701`; it is now
`3312a98627ecd6d14f801a2542868cba978c658d` — the head of this branch,
fast-forwarded. **This code is on `main`.**

That changes what this document is. It is no longer a merge gate; it is a
post-merge review, and the findings below are follow-up work. C1 in particular
should be treated as urgent rather than as a discussion item, because it affects
Anthony's real database right now.

It also means my earlier plan review
(`2026-07-30--claude-review-of-runtime-hardening-plan.md`, branch
`docs/claude/runtime-hardening-plan-review` @ `bcef304`) was written against
`aa4b25b` and describes this branch as unmerged. Findings C1 and C2 there are
now conditions of `main`, not warnings about a pending merge.

## Evidence levels

| Label | Meaning here |
|---|---|
| Software verification (Windows rig) | Command actually run on Anthony's ThinkPad, output recorded |
| Repository inspection | `git show` / `git diff`, no execution |

No Windows bench procedure and no actual-gear verification. No import was run
against Anthony's real database, and no NIC, BLE, or device write occurred.

### Checks I reran

| Command | Result |
|---|---|
| `python -m pytest -q tests` from `backend/`, app interpreter | **404 passed**, 118 warnings, 14.55 s |
| `python -m pytest -q backend\tests` from repository root | **5 failed, 399 passed**, 13.00 s |
| `npm test` (Vitest) in `app/` | **57 passed** (5 files), 9.50 s |
| `npm run build` in `app/` | **passed**, existing large-chunk warning only |

Interpreter: `C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe`.
Evidence level: software verification (Windows rig).

**Hermes' three reported results reproduce exactly** — 404 backend, 57 frontend,
build green. The root-level discrepancy is W7 and is not caused by this branch.

---

## Critical

### C1 — The migration creates a second Alembic head, and Anthony's real database is on the other one

`backend/migrations/versions/f12hoglib001_add_hog_fixture_library.py`:

```python
revision = "f12hoglib001"
down_revision = "c5f1a2b3d4e6"
```

`fix/claude/scanner-sweep-interface` carries
`d7c3a9f21b04_add_sweep_hints_to_network_subnets.py`:

```python
revision = 'd7c3a9f21b04'
down_revision = 'c5f1a2b3d4e6'
```

Two siblings, same parent, no merge revision. Verified by loading a combined
versions directory through Alembic's own `ScriptDirectory`:

```text
HEAD COUNT: 2
  head: d7c3a9f21b04 <- down_revision: c5f1a2b3d4e6
  head: f12hoglib001 <- down_revision: c5f1a2b3d4e6
```

Two consequences, and the first is live today:

1. **Right now**, `main` contains `f12hoglib001` but not `d7c3a9f21b04`. Anthony's
   real database was stamped `c5f1a2b3d4e6 -> d7c3a9f21b04` on 2026-07-29. So
   `flask db upgrade` from a current `main` checkout against that database cannot
   locate the revision the database says it is on. The database and the migration
   chain on `main` have diverged.
2. **When the scanner branch lands**, the two heads coexist and `flask db upgrade`
   fails with multiple head revisions until a merge revision exists.

**Fix:** re-parent `f12hoglib001` onto `d7c3a9f21b04` (they touch disjoint tables
— `fixtures`/`fixture_library_backups` versus `network_subnets` — so ordering is
free), or add an explicit merge revision. Re-parenting is cleaner while only one
of the two is on `main`; it gets harder once both are. Evidence level: software
verification (Windows rig) for the head count, repository inspection for the
revision graph.

This is the finding I would act on today.

---

## Warning

### W1 — The SQLite catalog lock reports "another operation is already running" when nothing is

`fixture_library.py:159-166` maps *any* `OperationalError` from `BEGIN IMMEDIATE`
to `FixtureLibraryBusyError`:

```python
elif dialect == "sqlite":
    session_connection = db.session.connection()
    try:
        session_connection.exec_driver_sql("BEGIN IMMEDIATE")
    except OperationalError as exc:
        raise FixtureLibraryBusyError(
            "Another fixture-library operation is already running"
        ) from exc
```

SQLite also raises `OperationalError` for `cannot start a transaction within a
transaction`, which has nothing to do with contention. Probed on an idle
in-memory SQLite database, single thread, single connection, no concurrency of
any kind:

```text
CASE A (clean session)          : OK - lock acquired, commit succeeded
CASE B (prior SELECT)           : OK - lock acquired, commit succeeded
CASE C (prior uncommitted write): FALSE BUSY -> Another fixture-library operation is already running
CASE D (nested lock)            : FALSE BUSY -> Another fixture-library operation is already running
```

Case B passes only because pysqlite defers `BEGIN` until the first write, so a
preceding `SELECT` is invisible. That is load-bearing behaviour nothing in the
code states.

**Reachability today:** all five current call sites take the lock before touching
the session, including `import_fixtures_excel` (`routes.py:505`, the lock opens
before `Fixture.query.all()`), so Case C is not reachable through shipped code.
Case D means the lock is simply not re-entrant.

**Why it is still a Warning:** the failure mode is a wrong answer, not an error.
An operator on the desktop build is told to wait for a concurrent operation that
does not exist, and the log says the same thing, so the true cause is invisible.
The next person to add a write before the lock, or to nest it, gets a 409 that
sends them looking for a second process.

**Fix (one line):** inspect the SQLite message and only treat genuine contention
(`database is locked`, `database table is locked`) as busy; re-raise everything
else so it surfaces as a real error. Evidence level: software verification
(Windows rig).

### W2 — `/api/fixture-library/status` rebuilds and hashes the whole catalog on every call

`fixture_library_routes.py:147` calls `fixture_catalog_checksum()`, which goes
through `snapshot_fixtures()` — every `Fixture` row materialised as an ORM object,
converted to a dict, JSON-serialised, SHA-256'd. `Database.jsx:34` calls that
endpoint on page load.

Measured at the real Hog 5.0.766 record count (29,936 rows), in-memory SQLite:

```text
fixture_catalog_checksum() first call  :    438.4 ms
fixture_catalog_checksum() second call :    405.4 ms
fixture_catalog_checksum() third call  :    390.6 ms
snapshot_fixtures() alone              :    440.9 ms
serialized snapshot size               :      9.50 MiB
```

~400 ms and 9.5 MiB of transient garbage per status request, on in-memory SQLite
— a file-backed database or MySQL over a socket will be slower. The Database page
pays this on every load.

To be fair to the design: the checksum is doing real work. Binding preview to
import and restore to a known catalog state (see the Looks Good section) is the
right call and needs a stable identity. The problem is the identity is computed
the expensive way and exposed on a status endpoint.

**Fix:** either compute the identity in SQL (`COUNT(*)` plus an aggregate over
`id`/`revision_id`/`library_version`), or keep the full-fidelity checksum for the
mutation paths and give `/status` a cheap identity. Evidence level: software
verification (Windows rig).

### W3 — The `run_desktop.py` desktop-SQLite bridge collision merged unresolved

Documented as C2 in the plan review. `main` now calls
`ensure_desktop_fixture_library_schema()`;
`fix/claude/scanner-sweep-interface` calls `upgrade_sqlite_schema(db.engine,
db.metadata)` at the same three lines, and additionally wires it into
`create_app()`'s desktop branch, which this branch does not.

The two are complementary rather than duplicate: the generic one refuses
`NOT NULL` without a default, the fixture-specific one rebuilds the table
precisely to relax `NOT NULL` on `wattage`/`weight`. Merging this branch first
did not resolve the question, it just decided who rebases. The scanner branch now
carries the conflict. Still needs one reconciled bridge. Evidence level:
repository inspection.

### W4 — `backend/config.py` changed beyond its declared reservation, and the new line is a hardcoded secret

`docs/coordination/active/hermes--hog-fixture-import.md` reserves
`backend/config.py` for the "fixture XML request-size bound only." The diff adds
two lines to `DevelopmentConfig`:

```python
SECRET_KEY = os.getenv("SECRET_KEY", "five12-development")
MAX_CONTENT_LENGTH = 26 * 1024 * 1024
```

`MAX_CONTENT_LENGTH` is the declared change. `SECRET_KEY` is not, and it is the
security-relevant one: it introduces a hardcoded credential fallback into the
file whose entire recent history was removing one. `fix/hermes/credential-config`
(merged at `aaca308`) exists specifically to "eliminate the hard-coded
database-password fallback," and lists `backend/config.py` among its reserved
paths.

The practical risk is low — the preview token this key signs is an
integrity binding between preview and import, not an authorization boundary, and
the endpoints are loopback with an origin check. But a hardcoded secret default
added silently, in that file, days after that cleanup, is exactly the change that
should have been announced in the reservation. Evidence level: repository
inspection.

### W5 — `ensure_desktop_fixture_library_schema` hardcodes the fixtures DDL and will go stale

`fixture_library.py:104-121` rebuilds `fixtures` from a literal `CREATE TABLE`.
Two problems:

1. The DDL is a second, divergent definition of a table SQLAlchemy already
   describes. The next column added to `Fixture` will be created by
   `db.create_all()` on a fresh desktop database and silently dropped by this
   rebuild on a legacy one, because the rebuild's column list is fixed.
   Divergence will not raise; it will just quietly lose the column.
2. `columns["wattage"]["nullable"]` at line 94 assumes `wattage` exists. On a
   desktop database predating that column the rebuild check raises `KeyError` at
   application startup, before anything can report a useful message.

Deriving the target columns from `Fixture.__table__` rather than a literal, and
guarding the `columns[...]` lookups, removes both. Evidence level: repository
inspection.

### W6 — The backup row has no size guard against `max_allowed_packet`

The snapshot is stored as one JSON column value. Measured above at 9.50 MiB for
the official library — Hermes measured 9.64 MiB and accepted it under a 16 MiB
`max_allowed_packet`, which matches. Nothing checks it.

A catalog with populated `notes` on top of a full vendor import, or a larger
future library, crosses 16 MiB and the failure arrives as a raw MySQL packet
error at commit time, inside `except Exception` → HTTP 500 "The fixture import
failed." Correct and safe — nothing is committed — but it gives the operator no
idea the fix is a server variable. Check the serialized length before insert and
say so. Evidence level: software verification (Windows rig) for the size,
repository inspection for the absent guard.

### W7 — The documented root-level test command is red on `main` (not caused by this branch)

```text
from backend/            : 404 passed
from repository root     : 5 failed, 399 passed
```

All five are `backend/tests/test_ble_scanner.py`, failing with
`ModuleNotFoundError: No module named 'app.five12_ble'` in the subprocess
children — the `BACKEND_DIR` two-dirnames-vs-three defect. `docs/coordination/README.md`
documents the root-level form as canonical, so `main`'s own documented command
now fails on `main`.

This branch did not introduce it and the fix is already written, on the unmerged
`feat/claude/preflight-doctor` (`a86b7cd`). Recording it here because it is now a
property of `main` and because a reviewer running the documented command against
this code will see five failures that have nothing to do with it. Evidence level:
software verification (Windows rig).

---

## Suggestion

### S1 — The DTD guard is a byte scan and can be sidestepped by encoding

`fixture_library.py:214-216` lowercases the entire upload and looks for
`b"<!doctype"` / `b"<!entity"`. A UTF-16-declared document encodes those bytes
with interleaved nulls and passes the check; ElementTree will still parse it.

Low actual risk — ElementTree does not resolve external entities and raises on
undefined ones, so there is no XXE behind the guard — but the guard reads as a
security control and is weaker than it looks. Parsing with an
`XMLParser` whose `doctype` handler rejects would be exact. Separately,
`xml_bytes.lower()` copies up to 25 MiB just to run the scan.

### S2 — `_required_text` shadows the imported `text`

`fixture_library.py:178` binds a local `text` inside a module that imports
`sqlalchemy.text` at line 14. Harmless today because the function does not use
it; the next edit that needs `text()` inside it gets a confusing `TypeError`.

### S3 — `delete_fixture` lost its generic exception handler

`routes.py:281-289` now catches only `FixtureLibraryBusyError`; `create_fixture`
and `update_fixture` keep their `except Exception` → logged 500. The inconsistency
means a delete failure produces a bare Flask 500 with no
`logger.exception` entry, so it will not appear in the log the other two write to.

### S4 — The origin check is a third independent CSRF decision

`_reject_foreign_origin` (`fixture_library_routes.py:34-38`) re-implements a
policy `claude/pr2-network-route-safety` already settled for the network write
endpoints. Two implementations will drift. Worth extracting one shared helper
once PR 2 lands, rather than a third copy at the next mutation endpoint.

### S5 — Document why restore reinserts explicit `id`s

`restore_fixture_backup` bulk-inserts the snapshot including its `id` field. That
is deliberate and correct — it preserves the identities `PatchRow` attribution
depends on, which is why the round-trip test survives — but nothing says so, and
it looks like an accident next to `replace_with_hog_library`, which lets ids be
assigned. One comment prevents someone "fixing" it.

---

## Looks Good

- **The preview-to-import binding is the strongest part of this change.** The
  signed token carries the file digest, parsed version, record count, the current
  catalog count, and the current catalog checksum; the import re-derives the file
  digest, then re-checks the catalog count and checksum *inside* the mutation lock
  (`fixture_library_routes.py:252-261`) before deleting anything. That closes the
  window between "operator reviewed a preview" and "the catalog is replaced"
  properly, rather than assuming it away. Restore does the same thing with a
  caller-supplied `expectedCatalogChecksum`.
- **Backup integrity is validated before it is trusted** — schema version, row
  count, and checksum, all three, in `validate_fixture_backup`, and restore takes
  its own rollback backup first. A restore that finds a corrupted snapshot fails
  without touching the catalog.
- **Identity stripping on edit** (`routes.py:252-266`): editing a vendor row's
  name or footprint clears `manufacturer`, `hog_uuid`, `revision_id`,
  `library_*`. The row stops claiming to be an official Hog profile the moment it
  stops being one. That is a distinction most implementations skip.
- **Unknown vendor data stays unknown.** `wattage`/`weight` import as `NULL`
  rather than 0, the model was widened to allow it, and the migration downgrade
  converts rather than failing. Fabricating zeros here would have quietly poisoned
  weight and power totals on real patch sheets.
- **The frontend search is done properly** — `PatchForm.jsx:23-50` debounces with
  `setTimeout` and cancels in-flight requests with `AbortController`, and the
  picker moved to the bounded `patch-profiles` endpoint instead of shipping 30k
  rows to the browser. `Database.jsx` calls `/status` once on load, not on an
  interval.
- **Search input is escaped before `ilike`** (`fixture_library_routes.py:67-74`):
  backslash, `%`, and `_` escaped with an explicit `escape="\\"`. Easy to skip.
- **Bounds are stated as constants and enforced at parse time** — 25 MiB, 100,000
  records, footprint 1–4096, UUID validated with `uuid.UUID`, library type
  allowlisted. The parser rejects before any database work begins.
- **The vendor library is not committed.** Import is operator-selected and local,
  and the coordination note is explicit that no redistribution right has been
  established.
- **Hermes' own leaf-agent review caught the two findings that mattered most**
  (the downgrade failing on NULL power data, and ordinary CRUD not participating
  in the catalog lock) and both fixes are real — the lock now wraps create,
  update, delete, and the Excel import, each returning 409 rather than racing.
- **All three reported check results reproduce exactly.** That is worth saying
  plainly: the self-report was accurate.

---

## Verdict

**Approve with non-blocking suggestions — with one exception that is not
non-blocking.**

The design is sound and, in places, better than it needed to be: the
preview/import binding and the backup validation are the work of someone who
thought about what happens when the operator walks away mid-task. The code that
touches Anthony's real fixture data is careful, transactional, and reversible.

**C1 is the exception and it needs action now.** It is not a defect in the import
logic; it is a revision-graph collision that the merge to `main` has already made
live. Anthony's database says it is on `d7c3a9f21b04`, and `main` has never heard
of that revision.

Everything else is follow-up:

- W1 and W5 are correctness landmines that are not currently reachable.
- W2 is a measured performance defect on a page-load path.
- W3 is an unresolved cross-branch decision that the scanner branch now inherits.
- W4 is a process point about an undeclared security-relevant change.
- W6 and W7 are diagnosability, not correctness.

## Recommended next actions

1. **Re-parent `f12hoglib001` onto `d7c3a9f21b04`, or add a merge revision** —
   before the scanner branch rebases, and before anyone runs `flask db upgrade`
   against the real database. Anthony should not run a migration until this is
   settled.
2. Decide the single `run_desktop.py` bridge (W3); the scanner branch rebase is
   blocked on it either way.
3. W1's one-line error-classification fix.
4. W2's cheap catalog identity for `/status`.
5. W5's metadata-derived rebuild, folded into whatever W3 decides — they are the
   same function by then.

## What I did not check

- I did not run the import against the official `summary.xml`; I do not have the
  vendor file, so Hermes' 29,936-record verification is unreproduced here. My
  scale measurements used synthesized rows at the same count.
- I did not verify the MySQL path at all. Hermes' MariaDB 11.4 container run is
  the only evidence for `GET_LOCK`, the 409 contention behaviour, and the backup
  round-trip under MySQL, and I did not reproduce it.
- I did not exercise the Database or PatchForm pages in a browser.
- I did not review `app/src/pages/Database.jsx` or `PatchForm.jsx` line by line —
  only the data flow relevant to W2, S5, and the Looks Good notes on debouncing.
- No import, restore, or migration was run against Anthony's real database.
