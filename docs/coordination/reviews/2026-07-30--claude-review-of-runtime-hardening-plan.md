# Review — Five12 Runtime and Desktop Hardening Implementation Plan

- **Date:** 2026-07-30
- **Reviewer:** Claude Code (local Windows session, `C:\dev\Five12-TheApp`)
- **Reviewed artifact:** `docs/superpowers/plans/2026-07-30-five12-runtime-desktop-hardening.md`
- **Reviewed commit (pinned):** `42c203856b9be4376c942d7618d3e6ff7cf8849b` on `docs/hermes/runtime-hardening-plan`
- **Baseline compared against:** `origin/main` at `aa4b25b9d2411ec9565ebcb918b3e302f9883701`
- **Scope:** read-only plan review per plan section 8.8. No application code was changed.

## Evidence levels used in this review

| Label | Meaning here |
|---|---|
| Software verification (Windows rig) | A command actually run on Anthony's ThinkPad, output recorded below |
| Repository inspection | `git show` / `git diff` / `git ls-tree` against fetched refs, no execution |
| Not verified | Stated as a reasoning step, explicitly not tested |

No Windows bench procedure and no actual-gear (console, node, CRMX, BLE device)
verification was performed for this review. Nothing below is labelled as
hardware evidence.

### The one command I ran

```powershell
# cwd C:\dev\Five12-TheApp, checkout feat/claude/preflight-doctor @ a86b7cd
& 'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q backend\tests
```

```text
5 failed, 408 passed, 101 warnings in 10.40s      (wall clock 12.4 s)
FAILED backend/tests/test_ble_scanner.py::test_second_process_cannot_take_the_adapter_and_reports_not_owner
FAILED backend/tests/test_ble_scanner.py::test_releasing_the_lock_lets_another_process_acquire
FAILED backend/tests/test_ble_scanner.py::test_lock_is_released_when_the_holding_process_dies
FAILED backend/tests/test_ble_scanner.py::test_stop_keeps_the_lock_when_the_join_times_out
FAILED backend/tests/test_ble_scanner.py::test_stop_logs_a_warning_when_the_join_times_out
```

Machine state at the time, which turns out to be the whole point (see W2): the
Five12 backend was **running** — PID 2868,
`"C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe" -m flask run --port 5000 --no-reload`,
owning port 5000. Evidence level: software verification (Windows rig).

---

## Critical

### C1 — The plan does not know that `feat/hermes/hog-fixture-import` exists

`grep -i 'hog\|fixture\|cintenna\|astera'` over the plan returns three hits, all
incidental (`fixture_routes.py` in the Phase 9 target list, "fixtures" in the
Phase 9 characterization list, "fixture" in the Task 11.1 data list). The branch
is absent from the section 4 branch order, absent from the section 8.3
owner/reviewer matrix, and absent from section 2's current-state assumptions.

`origin/feat/hermes/hog-fixture-import` (head `3312a98`, base `aa4b25b`, pushed
2026-07-29, owned by Hermes) changes:

```text
backend/app/models.py
backend/migrations/versions/f12hoglib001_add_hog_fixture_library.py
backend/app/__init__.py
backend/app/routes.py
backend/config.py
backend/run_desktop.py
backend/app/fixture_library.py            (new)
backend/app/fixture_library_routes.py     (new)
app/src/pages/Database.jsx
app/src/components/PatchForm.jsx
...17 files, +2380/-296
```

Section 8.4 prohibits parallel work on `backend/app/models.py` and migrations,
on `backend/app/__init__.py` startup lifecycle, and on `backend/app/routes.py`.
This branch holds all three and is unmerged. Phase 3 (Task 3.3 modifies
`backend/app/__init__.py`) and Phase 9 (route split) are both planned as if
`main` were the only claimant.

**Required:** add the branch to the section 4 order and the 8.3 matrix, and fix
its integration position before Phase 3 begins. Evidence level: repository
inspection.

### C2 — Two branches add a different desktop-SQLite schema bridge to the same three lines of `backend/run_desktop.py`

`feat/hermes/hog-fixture-import`:

```python
from app.fixture_library import ensure_desktop_fixture_library_schema
...
    db.create_all()
    ensure_desktop_fixture_library_schema()
    seed_fixtures(db, Fixture)
```

`fix/claude/scanner-sweep-interface` (head `adf4d34`):

```python
from app.sqlite_schema import upgrade_sqlite_schema
...
    db.create_all()
    upgrade_sqlite_schema(db.engine, db.metadata)
    seed_fixtures(db, Fixture)
```

This is not only a textual conflict. The two are **semantically complementary
and individually insufficient**:

- `upgrade_sqlite_schema` is generic — it derives additive nullable columns from
  `db.metadata`, refuses `NOT NULL` without a default, and refuses any non-SQLite
  engine so it cannot touch Alembic. It cannot relax an existing `NOT NULL`.
- `ensure_desktop_fixture_library_schema` is fixture-specific and *does* rebuild
  the `fixtures` table, which is exactly what is needed so imported Hog rows can
  hold `NULL` wattage/weight instead of a fabricated zero.

They are also wired in different places. The scanner branch calls
`upgrade_sqlite_schema` from **both** `run_desktop.py` and `create_app()`'s
desktop branch (`backend/app/__init__.py`); the Hog branch calls its bridge only
from `run_desktop.py`. So a desktop launch through `create_app()` would pick up
the new fixture columns from the generic pass and **not** the `NOT NULL`
relaxation — a partial upgrade that neither branch's tests cover, because
neither branch is aware of the other.

Plan Task 1.3 step 5 ("Add a safe desktop SQLite migration if the branch changes
persisted scanner metadata") is written as though this bridge does not exist yet.
It exists twice.

**Required:** decide the single reconciled bridge before either branch merges.
My recommendation: keep the generic `upgrade_sqlite_schema` as the one entry
point, called from both sites, and let it delegate table rebuilds to
registered per-table handlers — with the fixtures rebuild as the first handler.
That preserves the "refuses anything needing a real migration" property while
giving the Hog import the one rebuild it legitimately needs. Evidence level:
repository inspection.

### C3 — Task 0.2's Windows baseline command cannot run on Anthony's rig

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests
```

There is no `.venv` at the repository root on the Windows machine (verified:
`ls -d C:\dev\Five12-TheApp\.venv` → absent). The interpreter the application
actually runs on is
`C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe` — verified
present, and verified as the interpreter of the live backend PID 2868 above.

`origin/main`'s `docs/coordination/README.md:79` still carries only the Linux
`.venv/bin/python -m pytest -q backend/tests` form; the Windows line naming the
app interpreter exists **only** on the unmerged `feat/claude/preflight-doctor`
(`a86b7cd`). Task 0.2 copies the broken form into the plan, so the first
executable step of Phase 0 fails on the machine it is meant to baseline.

This is not a typo worth a Suggestion. Naming the interpreter *is* the fix for
the 2026-07-28 fault: the Windows rig used to test on PATH Python 3.14 while the
app ran on 3.12, and the two had different package sets — the test interpreter
was missing six requirements including `bleak`. A baseline captured on the wrong
interpreter is not a baseline. Evidence level: software verification (Windows
rig) for the interpreter identity, repository inspection for the README state.

### C4 — Task 1.2 re-specifies work that is already implemented and approved, and points at the wrong file

Section 2 states: "The active network-route-safety work may not yet have a
published remote branch." It does. `origin/claude/pr2-network-route-safety`,
head `beed760`, `+290` in `backend/app/routes.py` and `+445` in
`backend/tests/test_network_routes.py`. Per
`docs/coordination/active/claude--pr2-network-route-safety.md` on `main`, it was
approved by Hermes at `82ba5d4`, rebased onto merged `main`, and the only
unchecked acceptance box is "Windows bench test on a spare adapter (Anthony; no
agent can perform this)."

Task 1.2 then instructs the implementer to "Add failing tests for shell
metacharacters, newline injection, malformed adapter identifiers, invalid
CIDR/mask/gateway" and "Replace shell-string construction with argument-vector
subprocess execution." That is the content of the merged-and-approved branch.
Executing Task 1.2 as written produces a second implementation of a solved
problem.

Separately, Task 1.2 names `backend/app/network_routes.py` as the file to
modify. `network_routes.py` **does** exist on `main`, which makes this look
correct on a skim — but the injection-prone `/api/network/apply` and
`/api/network/dhcp` handlers that PR 2 fixed live in `backend/app/routes.py`.
A reviewer trusting the file reference would reserve the wrong path and collide
with PR 2 anyway.

**Required:** restate Task 1.2 as "land the approved branch after Anthony's
Windows bench test," not as an implementation task. Evidence level: repository
inspection.

---

## Warning

### W1 — Task 0.3 is already done; section 2's failure claim is stale

Section 2: "three BLE subprocess tests failed when invoked from the detached
repository-root worktree. The canonical test command and subprocess import path
must be made checkout-independent."

`feat/claude/preflight-doctor` at `a86b7cd` already fixed it —
`backend/tests/test_ble_scanner.py` computed `BACKEND_DIR` with two `dirname`
calls where the child needed three, so the children only imported when the cwd
happened to supply `backend/`:

```python
BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(scanner_mod.__file__)))
)
```

Confirmed by the run at the top of this document: invoked from the repository
root, there is no `ModuleNotFoundError`, and the file's children execute (the
five failures are a different cause — see W2).

Section 8.3 assigns "Reproducible baseline/test-path fix" to Hermes as
implementer with Claude reviewing. That collides with a pushed Claude branch.
Reassign or drop Task 0.3. Evidence level: software verification (Windows rig).

### W2 — The Task 0.2 baseline is not reproducible as specified, and I can show why

The five failures above are `test_ble_scanner.py`'s adapter-lock tests, and they
fail **because the Five12 backend was running** and holds the machine-wide
Bluetooth adapter lock. Stop the app and they pass; leave it running and they
fail. Nothing in the output says that — the assertion reads `assert '' == 'HELD'`,
which looks like a code defect.

Task 0.2 says "Record exact pass/fail counts" without specifying app-stopped or
app-running. Whoever captures the baseline records `408 passed` or `413 passed`
depending on an unstated machine condition, and then every later comparison is
measured against a coin flip. Worse, the natural reading of a red suite is "the
refactor broke BLE."

**Required:** Task 0.2 must state the app-stopped precondition and record it in
the baseline document. **Suggested alongside:** make the lock tests report the
holding process so the failure says "the Five12 app is running (PID n)" instead
of `assert '' == 'HELD'`. That is a small fix and it is already on my open list
from the 2026-07-30 handoff. Evidence level: software verification (Windows rig).

### W3 — Phase 6 under-scopes the polling sprawl by a factor of seven

Section 2 attributes "multiple independent polling intervals" to
`app/src/pages/NetworkMonitor.jsx`. That file has exactly one, at
`NetworkMonitor.jsx:501` (15 s). The sprawl is real but it is somewhere else:

```text
app/src/pages/Devices.jsx:83               setInterval(poll, POLL_MS)
app/src/pages/Devices.jsx:84               setInterval(hist, POLL_MS * 4)
app/src/pages/Devices.jsx:284              setInterval(loadUnits, 10000)
app/src/pages/Devices.jsx:499              setInterval(poll, 10000)
app/src/components/SacnUniverses.jsx:36    setInterval(load, POLL_MS)
app/src/components/devices/CintennaPanel.jsx:130  setInterval(poll, 5000)
app/src/pages/Console.jsx:181              setInterval(tick, 150)
app/src/pages/NetworkMonitor.jsx:501       setInterval(fetchDevices, 15_000)
```

(`app/src/vendor/dymo.connect.framework.js` also matches; vendor file, out of
scope.) Task 6.2 lists only `NetworkMonitor.jsx` as a modify target, so it would
centralize one interval out of eight and report polling as consolidated.
`Console.jsx:181` at 150 ms is a render tick rather than a network poll and
should be explicitly excluded rather than silently missed. Evidence level:
repository inspection.

### W4 — Section 4's branch-order placeholders are stale in three places

- Item 1, "`fix/<agent>/dead-root-migrations` — restore/recreate if the reviewed
  branch was deleted." Not deleted. `origin/chore/claude/remove-dead-migrations`
  head `06b1e3c`, Hermes-approved, both review suggestions applied.
- Item 2 is `origin/claude/pr2-network-route-safety` (see C4).
- Items 3 and 4 are `fix/claude/scanner-sweep-interface` (`adf4d34`) and
  `feat/claude/preflight-doctor` (`a86b7cd`). Section 2 says these "must be
  re-reviewed against prior findings before integration," which is correct, but
  the response round already happened: Hermes' three reviews landed on
  `docs/hermes/claude-branch-reviews` at `29e7d27` and my responses to all of
  them are the current heads. What is outstanding is Hermes' **re-review of the
  responses**, not a first review.

Use the real branch names and heads; `<agent>` placeholders invite a second
implementation. Evidence level: repository inspection.

### W5 — `docs/coordination/README.md` canonical-checks section is double-claimed

`feat/claude/preflight-doctor` already modifies that section (the Windows
interpreter line quoted in C3). Task 0.3 lists `AGENTS.md` and `CLAUDE.md` as
modify targets, and section 8.4 places `AGENTS.md`, `CLAUDE.md`, and shared
coordination rules on the no-parallel list. If Hermes owns Task 0.3 while the
preflight branch is unmerged, the two edit the same shared surface. Sequence the
preflight merge first, or hand Task 0.3's doc edits to whoever owns that branch.
Evidence level: repository inspection.

### W6 — One open severity question from the previous round is not settled by this plan

My 2026-07-30 response left one deviation deliberately open: the doctor's repo
identity check treats **behind upstream** as WARN and **diverged** as FAIL,
where Hermes asked for stale state to fail or require explicit override. My
argument was that a preflight blocking every launch for routine
behind-upstream gets switched off, which is the failure mode the script exists
to prevent.

Task 1.4's required cases cover port ownership, doctor exceptions, missing
dependencies, and runtime-mode reporting — repo staleness is not among them. So
the plan neither ratifies nor overrides the deviation, and Task 1.4 could be
marked complete with the disagreement still live. Add it to Task 1.4's required
cases with an explicit decision. It is a one-line change either way.

---

## Suggestion

### S1 — Electron protocol removal is much smaller than Phase 5's shape implies

`electron/main.js` is 222 lines on `main`. Its entire protocol surface is
`require('dgram')`, `parseSACN`, `parseArtNet`, `sacnMulticast`, and one socket
bound to `0.0.0.0` on 5568 (sACN) or 6454 (Art-Net). `electron/preload.js` is 19
lines exposing six channels: `network:start`, `network:stop`,
`network:subscribe`, `network:unsubscribe`, `network:universes`,
`network:channels`.

Task 5.1's inventory is worth doing, but it is an afternoon against six channels,
not a phase-scale deliverable. Consider folding it into Task 5.4's deletion gate
as a checklist rather than a standalone architecture document.

**The detail that matters more than the size:** the Electron socket is created
with `reuseAddr: true` and bound to `0.0.0.0`. So running Electron and the
Python listener simultaneously does **not** produce a bind error — both receive
traffic, and the duplicate-engine condition is silent. Task 5.4's deletion gate
says "UDP port ownership inspection shows one owner per listener"; that check
must count **processes holding the socket**, because a successful bind proves
nothing here. This is the same shape as the doctor's process-vs-port lesson: the
port-level view reported exactly one owner in the broken state. Evidence level:
repository inspection (I did not run both engines concurrently).

### S2 — Nobody in the 8.3 matrix can actually verify the Windows installer

Section 8.3 assigns "Electron thin shell/packaging" to Claude with Hermes
reviewing, and Task 11.2 requires "Clean Windows account/VM install, no
preinstalled Python dependency." A Claude Code cloud branch cannot do that, and
Hermes is on Linux. As written, Task 11.2 has no owner who can execute it.

Suggested split: Claude cloud implements the packaging branch; this local
Windows Claude Code session runs the clean-account install and records the
evidence; Hermes reviews the evidence rather than reproducing it. That should be
stated, because it is the one place where "independent reviewer reruns the
checks" is physically impossible.

### S3 — The Task 10.2 packaging spike must name Npcap and Bleak explicitly

Both are Windows-native-dependency traps we have already been bitten by. `scapy`
imports cleanly on Windows with no Npcap present — metadata check passes, real
import check passes — and then every send fails at runtime into a `log.debug`
(`backend/app/scanner.py:197`/`:199`). A PyInstaller bundle could therefore ship
an app that looks green and whose ARP sweep silently never runs. The spike
criteria list "native dependency behavior, Bleak/Windows support" generically;
name the two concrete traps and require a post-package *functional* check
(`conf.use_pcap`, and a real BLE adapter enumeration), not an import check.

### S4 — Exclude the BLE radio from the runtime restart allowlist

Task 6.1 proposes `POST /api/runtime/services/<name>/restart` "only for
allowlisted non-write services." The BLE radio service should be off that
allowlist or separately gated: it owns a machine-wide adapter lock whose
contention already breaks five tests (W2), and an operator-triggered restart
racing that lock is a support call waiting to happen.

### S5 — Section 2's measurements check out

For the record, since section 2 asks to revalidate: `backend/app/routes.py` 1190
lines (plan says ~1191), `backend/app/scanner.py` 491, `backend/app/sacn_listener.py`
434, `backend/app/five12_ble/scanner.py` 355. No `.github/workflows/` on `main`.
`app/package.json` defines `dev`, `build`, `preview`, `test`, `test:watch`. All
accurate at `aa4b25b`. Evidence level: repository inspection.

---

## Looks Good

- **Serial integration with per-branch worktrees and reservations.** Section
  8.4's prohibited-parallelism list names precisely the files where our real
  collisions have occurred (`models.py`, migrations, `__init__.py`, `routes.py`,
  lockfiles, `AGENTS.md`/`CLAUDE.md`). The rule is right; C1 and C2 are cases of
  the rule already being violated in flight, not of the rule being wrong.
- **Evidence-label discipline** (section 7 closing paragraph, Task 11.3) matches
  what both agents have been enforcing since 2026-07-27 and is the single most
  valuable convention in this collaboration.
- **Not deleting Electron code until every consumer is migrated** (Task 5.1 step
  5, Task 5.4 deletion gate) is the correct ordering, and the gate is specific
  enough to be checkable.
- **YAGNI constraints** — Task 3.2's "Do not introduce a general plugin
  framework" and Task 6.2's "Do not add WebSockets/SSE until measured polling
  load demonstrates need" — are well placed on exactly the two tasks most likely
  to sprawl.
- **Task 8.2's performance method** ("Measure baseline first. Set budgets from
  observed healthy behavior plus justified headroom; do not invent arbitrary
  production limits") is the right instinct and rare to see written down.
- **Task 7.2's adversarial redaction test** — seeding secrets into internal
  errors and proving they do not appear in the export — is a real test rather
  than an assertion of intent.
- **Section 8.5's handoff and review formats** match the conventions already in
  `docs/coordination/README.md`, including pinning the reviewed SHA. This review
  follows them.
- **Pitfall table.** "Test passes only from one cwd" and "Electron and Python
  bind the same UDP ports" are both real and both already observed on this rig.

---

## Verdict

**Request changes.**

The architecture is sound and I agree with the destination: Python owning
protocols and hardware, React owning presentation, Electron reduced to a shell,
browser-canonical development until packaging. The sequencing discipline is
better than what we have been doing informally.

What blocks it is that Phase 0 and Phase 1 are written against a repository
state that is roughly two days stale. Four Critical items — an unmerged Hermes
branch the plan does not know about (C1), a live two-branch collision in
`run_desktop.py` (C2), a Windows baseline command that cannot run (C3), and a
re-specification of already-approved work (C4) — mean the first two phases
cannot be executed as written. All four are correctable in the plan document
without changing the architecture.

## Recommended integration order (replaces section 4 items 1–4)

| # | Branch / action | Head | State |
|---|---|---|---|
| 1 | `chore/claude/remove-dead-migrations` | `06b1e3c` | Approved; merge independently, no prerequisites |
| 2 | **Decision:** reconcile the `run_desktop.py` SQLite bridge (C2) | — | Blocks 3 and 4; a decision, not a branch |
| 3 | `feat/hermes/hog-fixture-import` | `3312a98` | Needs Claude review (not yet performed); holds `models.py` + migration + `__init__.py` |
| 4 | `fix/claude/scanner-sweep-interface` | `adf4d34` | Awaiting Hermes re-review; rebase onto the reconciled bridge |
| 5 | `claude/pr2-network-route-safety` | `beed760` | Approved; blocked only on Anthony's Windows bench test |
| 6 | `feat/claude/preflight-doctor` | `a86b7cd` | Awaiting Hermes re-review; last because it edits `docs/coordination/README.md` and `start.ps1` |
| 7 | Phase 0 baseline (Task 0.2 only; 0.3 lands with 6) | — | Cheap once 1–6 are in; record the app-stopped precondition |
| 8 | Phase 2 ADR, then Phase 3 runtime manager | — | Phase 3 must start after 3 merges, per section 8.4 |

3 and 4 may swap; whichever goes second rebases onto the reconciled bridge.

## Proposed owner/reviewer split

I accept section 8.3's default with four amendments:

| Milestone | Implementer | Reviewer | Change from plan |
|---|---|---|---|
| Hog fixture-library import | Hermes (done) | **Claude** | Not in plan at all — add it |
| `run_desktop.py` bridge reconciliation | Whoever merges second | Other agent | New; C2 |
| Baseline / test-path fix (0.2, 0.3) | **Claude** | Hermes | Plan says Hermes; 0.3 already on `a86b7cd` |
| Network-route safety | — | — | Not an implementation task; land the approved branch (C4) |
| Windows installer verification (11.2) | **Local Claude Code (this session)** | Hermes reviews evidence | Plan has no owner who can run it (S2) |

Everything else in the 8.3 matrix I agree with as written, including Hermes
owning the runtime contracts and `RuntimeManager`, and Claude reviewing them
before any downstream implementation starts.

## What I did not check

- I did not run the frontend suite or the production build.
- I did not run the plan's Linux reviewer commands; there is no Linux checkout here.
- I did not review `feat/hermes/hog-fixture-import`'s code beyond the file list,
  the coordination note, and the `run_desktop.py`/`__init__.py` diffs needed for
  C1 and C2. That branch still needs its own review.
- I did not exercise Electron, and I did not run the Python and Electron
  listeners concurrently to confirm the `reuseAddr` behaviour asserted in S1.
- No NIC, BLE, CRMX, or device write of any kind was performed.
