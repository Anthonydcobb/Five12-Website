# Active work — delete the dead root-level migrations/ copy

- **Owner:** Claude
- **Branch:** `chore/claude/remove-dead-migrations`
- **Workspace:** sibling worktree `C:\dev\Five12-worktrees\claude-dead-migrations`
- **Base SHA:** `aa4b25b` (`origin/main`)
- **Status:** review
- **Last updated:** 2026-07-29

## Goal

Leave exactly one Alembic history. There were two, and which one you got
depended on the directory you ran `flask db` from.

## Why

Flask-Migrate resolves its migrations directory relative to the **working
directory**. With a copy at the repository root and the real one at
`backend/migrations/`, running `flask db` from the repo root silently drove the
dead chain. `docs/network-state.md:362` already recorded that as a lesson; the
trap outlived the lesson.

It cost this session a confidently wrong diagnosis. An agent — me — read the
root copy, found a chain whose head did not match the database and which
created none of the network tables, concluded the project could not deliver a
schema change by migration at all, and published that to a branch before
catching it. Nothing was broken except which folder was being read. The wrong
claim and its retraction are both in the record on
`fix/claude/scanner-sweep-interface` (`fb15bbc`, retracted by `72797cc`).

**The instructions were part of the trap.** `AGENTS.md:51` and `CLAUDE.md:51`
both said the schema was "managed via Flask-Migrate/Alembic in `migrations/`" —
pointing squarely at the dead copy. An agent following the repository's own
instructions landed in the wrong directory.

## Changes

- **Deleted `migrations/`** — 33 tracked files: 14 revisions, `env.py`,
  `alembic.ini`, `README`, and 15 committed `__pycache__/*.pyc` that should
  never have been tracked. Recoverable from git history if ever wanted.
- **`AGENTS.md` and `CLAUDE.md`** now name `backend/migrations/` and say to run
  `flask db` from `backend/`, since the resolution is working-directory
  relative. This is the fix that matters most: it is what the next agent reads.
- **`docs/architecture/ble-integration-map.md`** likewise.
- **`.gitignore`** keeps the anchored `/migrations/` rule — `flask db init` from
  the repo root would recreate the trap — with the comment updated to say the
  copy is gone and why the anchor matters.
- **`backend/tests/test_migrations_layout.py`** — six guards: no root-level
  `migrations/`, the real directory exists and is populated, the docs name it,
  unique revision ids, no dangling `down_revision`, exactly one base and one
  head. Filesystem only, no database, runs anywhere.

Left alone deliberately: `docs/superpowers/plans/2026-05-21-network-monitoring-dashboard.md`
refers to `migrations/versions/`. It is a historical plan describing what was
done at the time, not instructions to follow now.

## Reserved paths

- `migrations/**` (deleted)
- `AGENTS.md`, `CLAUDE.md` — **agent instructions, named in README rule 4 as
  collision-prone.** Claimed here before editing, per rule 3, and flagged for
  Hermes explicitly: these are the files every agent reads, so a change to them
  deserves a second opinion even when it is a one-line correction.
- `.gitignore`
- `docs/architecture/ble-integration-map.md`
- `backend/tests/test_migrations_layout.py`

## Must-not-touch paths

- `backend/migrations/**` — the real history, untouched by this branch
- Everything owned by `claude--preflight-doctor.md`,
  `claude--scanner-sweep-interface.md`, and PR 2

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| `python -m pytest tests/test_migrations_layout.py` | **6 passed** | software — no hardware claim |
| `python -m pytest` (full) | **384 passed, 5 failed** (the BLE lock tests — the app is running and holds the adapter lock; reproducible on clean `main`) | software — no hardware claim |
| Whole chain applied to an empty MySQL database **after** the deletion, then compared to the models | 12 tables, `alembic_version` = `c5f1a2b3d4e6`, **0 differences** | database — disposable MySQL |

Evidence labels corrected after review: an earlier version of this table marked
all three as `verified on actual gear`. That label exists for **hardware**
behaviour (README rule 8), and applying it to filesystem and database checks
devalues it for the claims that need it. Nothing here touched lighting gear.

The last one is the one that matters: it proves deleting the root copy did not
disturb the real chain. Scratch database created and dropped by the check; the
live database was only read.

## Risks and skipped checks

- Anyone with a shell habit of running `flask db` from the repo root will now
  get a loud failure instead of silently driving the dead chain. That is the
  intent, but it is a behaviour change worth knowing about.
- The deleted `env.py` and `alembic.ini` at the root differed from
  `backend/migrations/`'s copies only in being unused; they were not compared
  line by line, because nothing runs them.

## Handoff / next action

Review by Hermes, with attention to the `AGENTS.md` / `CLAUDE.md` edit.


## Rebased onto current `main` by cherry-pick — 2026-07-30

Per Hermes' re-review: **controlled two-commit cherry-pick, not a wholesale
merge of the old branch tree.** That advice was right and the reason is now
concrete — the branch forked at `aa4b25b`, and `main` has since gained the Hog
fixture library, the single-head migration fix, the desktop schema bridge, the
preflight doctor, and Hermes' fixture-error work. Merging that tree wholesale
would have reverted parts of all of it.

New branch `chore/claude/dead-migrations-on-main`, off `main` at `1c86d1d`:

```text
c0d8761  chore: delete the dead root-level migrations/ copy          (was fbdebf5)
77ae462  docs: address Hermes review - discriminating doc guard...   (was 06b1e3c)
```

Both applied with **no conflicts**.

### Verification on the cherry-picked tree

| Check | Result |
|---|---|
| `pytest -q backend/tests/test_migrations_layout.py` | **6 passed** |
| `pytest -q backend/tests` from the repository root | **458 passed** (452 + the 6 new) |
| Alembic heads | **1** — `f12hoglib001` |
| Root `migrations/` files remaining | **0** (was 33) |
| `backend/migrations/versions/` files | 16, intact |
| `flask db current` against the **live** database | `f12hoglib001 (head)` |

That last row is the one worth having: the live MySQL database's migration
tooling still resolves with the dead copy gone, which is the thing deleting it
could plausibly have broken. Read-only, no schema change.

### One remaining reference, deliberately not changed

`docs/superpowers/plans/2026-05-21-network-monitoring-dashboard.md` lines 262 and
270 still say `migrations/versions/` unqualified. It is a historical plan
document — a record of what was planned in May, not live instruction — so
rewriting it would be falsifying the record rather than fixing a trap. The
anchored `.gitignore` rule now prevents a recreated root copy from being
committed regardless. Flagged rather than silently edited; if Hermes would
rather it carry a correction note, that is a one-line addition.

### Status

Pushed for review. Not merged.
