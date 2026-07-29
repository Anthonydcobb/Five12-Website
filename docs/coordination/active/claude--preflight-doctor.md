# Active work — preflight doctor

- **Owner:** Claude
- **Branch:** `feat/claude/preflight-doctor`
- **Workspace:** local integration checkout `C:\dev\Five12-TheApp` (branch, not `main`)
- **Base SHA:** `aa4b25b` (`main`)
- **Head SHA:** `b8f567f`
- **Status:** review
- **Last updated:** 2026-07-29

## Goal

Add `scripts/doctor.ps1`, a fast read-only preflight that checks the invariants
behind the six silent faults of 2026-07-28/29, and call it from `start.ps1`
before dev mode launches anything.

Every check maps to a fault that produced **no** error in UI, logs, or startup
output. The app ran; it just ran wrong.

| # | Fault (2026-07-28/29) | Check |
|---|---|---|
| 1 | Shortcut launched a stale OneDrive clone on an old branch | Repo identity |
| 2 | `flask run` without `--no-reload` → two processes racing the BLE adapter lock | Process hygiene |
| 3 | `websocket-client` missing from the app runtime, swallowed by a blanket `except` | Python deps (app interpreter) |
| 4 | `.env` had `DB_PASS`, `config.py` reads `DB_PASSWORD` | `.env` completeness |
| 5 | Launcher did not set `FIVE12_BLE_TOOLS` / `FIVE12_BLE_WRITE` | Feature gates |
| 6 | All four show NICs drifted to Windows network category `Public` | Network |

## Acceptance criteria

- [x] One `OK` / `WARN` / `FAIL` line per check, plus the exact fix command on every failure.
- [x] Non-zero exit on any `FAIL`.
- [x] Python deps checked against the **app** interpreter
      `C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe`,
      not the test interpreter on `PATH`.
- [x] `.env` key list derived from `config.py` at runtime, never hardcoded.
- [x] No secret values printed — presence and length only.
- [x] Read-only: no firewall, network-category, `.env`, or package changes.
- [x] Under ~3 s in default mode (1.9 s measured); `-Full` is 3.6 s.
- [x] Pester tests prove each check FAILS when its invariant is violated — 44 passed.
- [x] pytest tests for the Python probe helper — 20, in the canonical suite.
- [x] `start.ps1` dev mode runs the doctor first.
- [ ] Independent review (Hermes).

## Reserved paths

- `scripts/doctor.ps1`
- `scripts/Five12Doctor.psm1`
- `scripts/doctor_probe.py`
- `scripts/tests/Five12Doctor.Tests.ps1`
- `backend/tests/test_doctor_probe.py`
- `start.ps1`
- `docs/coordination/active/claude--preflight-doctor.md`

## Must-not-touch paths

- `backend/app/routes.py`, `backend/tests/test_network_routes.py` (PR 2, `claude--pr2-network-route-safety.md`)
- `backend/config.py`, `.env`, `.env.example`, `.gitignore` (PR 1 contract, `hermes--credential-config.md`) — read only
- `backend/app/models.py`, migrations, frontend manifests and lockfiles
- All `backend/app/five12_ble/` paths

## Interfaces and contracts

- Reads, does not define, the `DB_HOST` / `DB_USER` / `DB_PASSWORD` / `DB_NAME`
  contract established by PR 1.
- Reads `GET /api/network/subnets` when the backend is up, otherwise the
  `network_subnets` table directly. Adds no route.
- Reads `GET /api/ble/capabilities` for authoritative gate state on a running
  backend. That route exists only when `ENABLE_BLE_TOOLS` is on, so 404 is
  itself the answer.
- `scripts/doctor_probe.py` emits a single JSON object on stdout. That shape is
  internal to the doctor and not a public contract.

## Dependencies and blockers

None. Nothing here blocks or is blocked by PR 2.

## Decisions and trade-offs

**Severity assignment is deliberate, and not uniform.**

- *Missing NIC for a configured subnet* → `WARN`, not `FAIL`. Off-site, show
  NICs are legitimately unplugged. A doctor that blocks every at-home launch
  gets switched off, and a switched-off doctor catches nothing.
- *NIC inside a configured subnet at the wrong prefix length* → `FAIL`. That is
  drift, not absence.
- *Show NIC on category `Public`* → `FAIL`. This is fault 6 exactly; it blocks
  inbound traffic and silently breaks Hog console show networking.
- *Working tree dirty* / *on `main`* → `WARN`. Coordination rule 1 says `main`
  is integration-only, but Anthony launching from `main` is not a fault.

**Dependency presence is checked from installed distribution metadata by
default, and by real import under `-Full`.** Importing `pandas`, `scapy`, and
`bleak` for real costs seconds every launch. Metadata is ~0.2 s and catches the
fault that actually happened (package simply not installed). `-Full` catches the
rarer broken-install case.

**"Show NIC" is derived, not configured.** A show NIC is an interface whose
IPv4 falls inside a configured subnet *at that subnet's prefix length*. This
matters: the venue Wi-Fi at `172.16.10.228/23` sits inside the Management
`172.16.0.0/16` subnet and is legitimately `Public`. Matching on prefix length
keeps the doctor from demanding that the venue Wi-Fi be made Private.

**Fault 2 is detected at the process level, not the port level.** Werkzeug's
reloader runs two processes but only the child binds port 5000, so counting
port owners would report `1` in the exact broken state. The doctor counts
`flask run` command lines and inspects parent/child relationships as well as
port owners.

## Plan or spec

Spec is the task brief; this note is the plan. No separate
`docs/superpowers/plans/` entry — the scope is one script and its tests.

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| `pwsh -File scripts\tests\Run-DoctorTests.ps1` | **44 passed, 0 failed** (Pester 3.4.0) | verified on actual gear |
| `cd backend && python -m pytest` | **404 passed**, 101 pre-existing warnings | verified on actual gear |
| `cd backend && python -m pytest tests/test_doctor_probe.py -q` | **21 passed** before the unused-import cleanup; 20 after | verified on actual gear |
| `pwsh -File scripts\doctor.ps1` | exit 1 — real finding, see below | verified on actual gear |
| `pwsh -File scripts\doctor.ps1 -Full` | exit 1, 3.6 s | verified on actual gear |
| `"n" \| pwsh -File .\start.ps1 -Mode dev` | doctor ran, FAILed, prompted, aborted, exit 1; nothing launched | verified on actual gear |
| `git diff --cached --check` | clean | verified on actual gear |

### Fault reproductions — each check was made to fail for real

| Fault | How it was reproduced | Result |
|---|---|---|
| 2 (one process, no `--no-reload`) | started the real backend with `flask run --port 5000` (no flag), `FIVE12_NETWORK_TOOLS=0` so it did not ARP-sweep the show subnets | `FAIL Process hygiene — PID 57800 is running flask without --no-reload`; process stopped, 0 listeners left |
| 2 (more than one backend) | two real backends on 5000 and 5001 | `FAIL — 2 independent flask processes (PIDs 33844, 15584)` while **only 1** was bound to port 5000, which is exactly why port counting alone cannot catch this |
| 3 (missing package) | no injection needed — `scapy`, `puresnmp`, `t61codec` and `verlib` are genuinely absent from the app interpreter today | `FAIL Python deps — not installed: scapy, puresnmp, t61codec, verlib` |
| 4 (`DB_PASS` rename) | ran `doctor_probe.py --repo-root` against a throwaway fixture tree whose `.env` had `DB_PASS` and whose `config.py` read `DB_PASSWORD` | `missing_required: ["DB_PASSWORD"]`, `unreferenced_in_env_file: ["DB_PASS"]`, database failed closed; the fixture's value never appeared in the output |
| 5 (gates off) | the live backend above ran with both gates unset | doctor read `GET /api/ble/capabilities`, got 404, and reported `FIVE12_BLE_TOOLS = OFF (running backend, GET /api/ble/capabilities)` — the authoritative source, not a guess |
| 6 (Public category) | real NICs and real subnets, with the category list flipped to `Public` **in memory only** | `FAIL` naming HOG, sACN, COMS and Management with a `Set-NetConnectionProfile` fix each; `Get-NetConnectionProfile` immediately afterwards confirmed the machine was unchanged |
| 1 (OneDrive clone) | unit test only — `Test-Five12RepoIdentity` with a OneDrive root | `FAIL`, fix points at `C:\dev\Five12-TheApp`. Not reproduced live; that would mean creating a second clone. |

### Real finding, not a demo

On this rig today the doctor exits 1 for a genuine reason: four packages in
`backend/requirements.txt` — `scapy`, `puresnmp`, `t61codec`, `verlib` — are
**not installed on the app interpreter**, plus nine version drifts. `scapy` is
the one that matters: `backend/app/scanner.py:197` calls `_scapy_scan`, and
line 199 swallows the failure into `log.debug`, so the active ARP sweep has
been silently degrading to the OS ARP cache. This is fault 3's exact shape in
a different package. The doctor does not install anything; the fix line is:

```
& 'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pip install -r 'C:\dev\Five12-TheApp\backend\requirements.txt'
```

Anthony's call whether to run it — `scapy` on Windows also wants Npcap, which
is a separate operator decision.

## Commits

- `b8f567f` feat: add preflight doctor and run it before dev-mode launch

## Risks and skipped checks

- Pester on this machine is **3.4.0** (the Windows-bundled version). Tests are
  written in Pester 3/4 syntax (`Should Be`), which Pester 5 rejects. The runner
  pins `-MaximumVersion 4.99` and fails loudly rather than silently skipping.
- The doctor reports Windows network categories but must never change them.
  Category and firewall changes stay the operator's.
- Fault 1 (the OneDrive clone) is covered by unit test, not by a live
  reproduction. Reproducing it for real means standing up a second clone.
- The reloader's *two-process* form was proven by unit test and by two real
  independent backends. The live single-backend run did not spawn a second
  process because `flask run` only starts the reloader in debug mode — the
  command-line check (`--no-reload` absent) is what fired, which is the same
  invariant start.ps1's comment calls load-bearing.
- `-Full` (3.6 s) exceeds the ~3 s budget by design; that is why it is opt-in.

## Handoff / next action

Branch pushed and ready for independent review by Hermes. Two things for
Anthony, both of them operator decisions the doctor deliberately will not make:

1. Decide whether to install the four missing packages (see "Real finding").
2. Nothing else — no network, firewall, or `.env` change is requested.
