# Active work — preflight doctor

- **Owner:** Claude
- **Branch:** `feat/claude/preflight-doctor`
- **Workspace:** local integration checkout `C:\dev\Five12-TheApp` (branch, not `main`)
- **Base SHA:** `aa4b25b` (`main`)
- **Head SHA:** `7ac118f`
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

A seventh check, **Packet capture**, was added after the first pass exposed a
false green in the doctor itself — see "Fault 3 has a second face" below.

## Live results in the first two days

The doctor has already caught two real faults on Anthony's rig, neither of them
staged:

1. **Fault 6 recurred, 2026-07-29.** All four show NICs (`HOG`, `sACN`, `COMS`,
   `Management`) were verified `Private` during development and had drifted to
   `Public` roughly an hour later, on the next `start.ps1`. The doctor FAILed
   and blocked the launch; Anthony ran the four `Set-NetConnectionProfile`
   lines and the recheck came back clean. Worth noting for whoever picks this
   up: **this drifts on its own**, so a one-time fix is not a fix. NordVPN /
   NordLynx is present on this machine and adapter re-connects create fresh
   profiles that default to `Public` — a plausible cause, not a confirmed one.
2. **`scapy` was missing from the app interpreter** and had been for an unknown
   period, silently degrading ARP discovery to the OS cache via the swallowed
   failure at `backend/app/scanner.py:199`. Now installed (2.6.1), along with
   `puresnmp`, `t61codec`, `verlib`. Confirmed functional, not merely
   importable: `conf.use_pcap = True`, 18 interfaces visible.

## Fault 3 has a second face

Installing `scapy` would have turned the Python deps line green **without**
restoring the ARP sweep: on Windows scapy imports cleanly with no Npcap
present, so both the metadata check and the `-Full` real-import check pass
while every packet send still fails — into the same `log.debug` that hid the
original fault.

Npcap 1.88 turned out to already be installed here, so the sweep genuinely is
back. But the doctor could not have told the difference, and a preflight that
cannot distinguish "working" from "importable" is the exact failure it exists
to prevent. Hence the **Packet capture** check:

- fast path (~32 ms): `wpcap.dll` on disk, in Npcap's own directory or in
  WinPcap-compatible mode, plus the `npcap` service state
- `-Full`: asks scapy directly for `conf.use_pcap`, which outranks anything
  inferred from the filesystem
- `INFO` rather than a second `FAIL` when scapy is simply absent — the Python
  deps check already owns that fact — and `INFO` when scapy is not a
  requirement at all

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
- `backend/requirements.txt` (one line: the `requests` pin — see "Version pins")
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
| `pwsh -File scripts\tests\Run-DoctorTests.ps1` | **51 passed, 0 failed** (Pester 3.4.0; 44 before the Packet capture check) | verified on actual gear |
| `cd backend && python -m pytest` | **406 passed**, 101 pre-existing warnings (404 before) | verified on actual gear |
| `scripts\doctor.ps1 -Full -Detailed` | `OK Packet capture — capture driver present (wpcap.dll 1.10.6); scapy reports conf.use_pcap = True` | verified on actual gear |
| `scripts\doctor.ps1 -PythonExe C:\Python314\python.exe` | `FAIL Python deps — not installed: pytz, scapy, puresnmp, t61codec, verlib, bleak`; `INFO Packet capture — scapy is not installed`. A live demonstration of the interpreter split that hid fault 3. | verified on actual gear |
| doctor timing after the new check | 2.1 s steady default, 6.0 s `-Full` | verified on actual gear |
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

| Packet capture | ran the whole doctor against the test interpreter, which genuinely has no scapy | `INFO Packet capture — scapy is not installed, see the Python deps line`, no double-FAIL. Driver-absent and service-stopped paths are Pester-tested; uninstalling Npcap to prove them live was not worth breaking the rig. |

### Real finding, not a demo

On its first real run the doctor exited 1 for a genuine reason: four packages
in `backend/requirements.txt` — `scapy`, `puresnmp`, `t61codec`, `verlib` —
were **not installed on the app interpreter**. `scapy` is the one that
mattered: `backend/app/scanner.py:197` calls `_scapy_scan` and line 199
swallows the failure into `log.debug`, so the active ARP sweep had been
silently degrading to the OS ARP cache. Fault 3's exact shape in a different
package.

**Resolved 2026-07-29.** The four were installed at their pinned versions on
the app interpreter only, and verified functional rather than merely present:
`conf.use_pcap = True`, 18 interfaces visible, Npcap 1.88 service running.

### Version pins — resolved 2026-07-29

The nine drifts are gone. The direction turned out to be the opposite of my
first assumption, which is worth stating because it changes the right answer:
for **eight** packages the installed version was *older* than the pin, so this
was a forward sync, not a rollback. Only `requests` was installed newer
(2.34.2) than pinned (2.32.3).

What was done:

1. Raised the `requests` pin to `2.34.2` — the one line changed in
   `backend/requirements.txt`. Downgrading an HTTP/TLS library to satisfy a
   stale pin is a regression risk with no upside.
2. `python -m pip install -r requirements.txt` on the **app interpreter only**,
   which upgraded `Flask 3.1.0→3.1.1`, `SQLAlchemy 2.0.40→2.0.41`,
   `click 8.1.8→8.2.0`, `numpy 2.2.4→2.2.6`, `greenlet 3.1.1→3.2.2`,
   `Mako 1.3.9→1.3.10`, `python-dotenv 1.1.0→1.2.2`,
   `typing_extensions 4.13.1→4.13.2`, and left `requests` alone.

`click 8.1→8.2` was the only non-patch bump. Flask 3.1.1 requires
`click>=8.1.3` and the app only ever invokes `flask run`, so the surface is
small — but it is the one to look at first if anything odd appears.

Rollback snapshot of all 63 packages was taken before the change
(`pip freeze`), outside the repo.

**Verified by running the app, not just by reading the table.** A green
dependency line proves nothing on its own, so the backend was started exactly
the way `start.ps1` starts it — app interpreter, `--no-reload`, both BLE gates
on — and driven:

| Endpoint | Result |
|---|---|
| `GET /api/network/subnets` | 200, 507 bytes |
| `GET /api/ble/capabilities` | 200, 109 bytes (so the tools gate is on and `bleak` imported) |
| `GET /api/ble/status` | 200, 86 bytes |
| `GET /api/network/devices` | 200, 18670 bytes |

No tracebacks in the backend log. Two lines in it are worth keeping as
evidence — **verified on actual gear**:

- `sACN: listening on :5568 across 9 interface(s)` followed by
  `universe 1 source 10.0.0.5 "Processor, Netnumber 5, Output 1"` through
  `Output 6` — live console output being received on the upgraded stack.
- `INFO in scanner: Scanning 172.31.0.0/16` — the scapy ARP sweep running,
  which it had not been doing at all while scapy was missing.

Backend stopped afterwards; 0 listeners left on 5000.

**Caveat, and it is the interesting one:** `cd backend && python -m pytest`
runs on the *test* interpreter, which was **not** upgraded. So 406 passing
tests validate the code, not this upgrade. The live smoke test above is the
only thing that exercised the new versions. This is the same two-interpreter
split that hid fault 3, showing up as a gap in test coverage rather than as a
runtime bug — see "Still open".

## Commits

- `b8f567f` feat: add preflight doctor and run it before dev-mode launch
- `71ea7ec` docs: claim preflight-doctor scope and record verification
- `91f643e` fix: add UTF-8 BOM so Windows PowerShell 5.1 parses these scripts
- `1adc6e8` docs: record head SHA and both-shell verification
- `7ac118f` feat: check that scapy can actually capture, not just that it imports

Both shells verified at `91f643e`: `powershell` 5.1 and `pwsh` 7.6.4 each run
the doctor (2.3 s / 1.7 s) and the Pester suite (44 passed, 51 as of `7ac118f`).

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

Branch pushed and ready for independent review by Hermes at `7ac118f`.

Nothing is blocked on Anthony. The two live findings are both resolved: the
show NICs are back on `Private` and the four packages are installed and
verified functional.

Open, in rough priority order:

1. **Independent review** (Hermes). The judgement calls most worth a second
   opinion are the non-uniform severity (absent NIC = `WARN`, drifted prefix =
   `FAIL`) and the show-NIC derivation rule.
2. **Why do the NIC categories drift?** The doctor now catches it every launch,
   which is the important half, but something is changing them. Suspicion falls
   on VPN adapter re-connects; unproven.
3. **The test suite does not run on the interpreter the app runs on.** This is
   the root of fault 3 and it is still there: `cd backend && python -m pytest`
   uses Python 3.14 from `PATH`, which as of today is missing six of the app's
   requirements including `bleak`, while the app runs on Python 3.12 at
   `%LOCALAPPDATA%\Programs\Python\Python312`. Every dependency upgrade is
   therefore untested by CI-equivalent means; today's was covered by a live
   smoke test instead, which does not scale.

   Not fixed here because it is a real decision, not a chore: pointing the
   tests at the app interpreter needs `pytest` installed there, and syncing the
   3.14 environment to `requirements.txt` may not even be possible for every
   pin. Worth a decision from Anthony and Hermes rather than a unilateral move
   from me. **Recommendation:** run the tests on the app interpreter, and let
   the doctor's Python deps check become the thing that keeps both honest.
