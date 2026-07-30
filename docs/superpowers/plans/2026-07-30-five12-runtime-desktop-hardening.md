# Five12 Runtime and Desktop Hardening Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task, with an independent spec-compliance review followed by code-quality review for each implementation branch.

**Goal:** Turn Five12 from a strong internal prototype into a stable, observable application whose Python backend exclusively owns network and Bluetooth services, while preserving browser-first development and preparing a thin, distributable Electron desktop shell.

**Architecture:** Browser/Vite development becomes the canonical environment. A Python runtime manager owns passive listeners, active discovery, BLE, device adapters, lifecycle, health, and clean shutdown. React consumes versioned local API snapshots; Electron eventually becomes a thin launcher/window/packaging layer and contains no protocol engine.

**Tech Stack:** Python 3.12, Flask 3, SQLAlchemy/Alembic, pytest, React 19, Vite 5, Vitest, Electron 31, Windows 11, sACN/E1.31, Art-Net, ARP/ping, BLE/Bleak.

---

## 1. Scope and non-negotiable decisions

1. Five12 is not being reduced to fewer protocols. Its network and device capabilities are core product value.
2. Browser development at `http://localhost:5173` is canonical until the desktop release phase.
3. Electron remains in the repository but is experimental until it becomes a thin shell.
4. Python is the only owner of show-network sockets, OS network commands, BLE, device adapters, and the database.
5. React owns presentation and operator intent; it does not own hardware or protocol lifecycles.
6. Passive observation, active discovery, and device writes remain separate safety levels.
7. No device write becomes automatic as part of this refactor.
8. No database migration runs against Anthony's real Five12 database until backup/restore is proven on a disposable copy.
9. Every service must expose status and support idempotent start, idempotent stop, and bounded shutdown.
10. New scanners/device families are paused until the single-flight discovery and runtime-diagnostics milestones are complete.

## 2. Current-state assumptions to revalidate at execution time

- Baseline inspected: `origin/main` at `aa4b25b9d2411ec9565ebcb918b3e302f9883701` on 2026-07-30.
- Current application is approximately 144 source files and 24,156 source lines.
- `backend/app/routes.py` is approximately 1,191 lines.
- `backend/app/scanner.py` is approximately 491 lines.
- `backend/app/sacn_listener.py` is approximately 434 lines.
- `backend/app/five12_ble/scanner.py` is approximately 355 lines.
- `electron/main.js` currently contains sACN/Art-Net socket and parser behavior duplicated by Python services.
- `app/src/pages/NetworkMonitor.jsx` contains multiple independent polling intervals.
- The backend suite passed when run from `backend/`, but three BLE subprocess tests failed when invoked from the detached repository-root worktree. The canonical test command and subprocess import path must be made checkout-independent.
- `app/package.json` currently defines `test`, `test:watch`, and `build` scripts.
- No workflow files were present under `.github/workflows/` on the inspected `origin/main`.
- `origin/fix/claude/scanner-sweep-interface` and `origin/feat/claude/preflight-doctor` exist and must be re-reviewed against prior findings before integration.
- The active network-route-safety work may not yet have a published remote branch. Its active coordination record is authoritative.

Do not assume these remain true. Re-fetch and record the exact baseline before touching code.

## 3. Target runtime model

```text
Electron (desktop release only)
├── starts/stops packaged backend
├── opens application window
├── enforces loopback-only navigation and secure preload
├── handles installer/update/lifecycle
└── contains no sACN, Art-Net, ARP, BLE, or vendor protocol code

React
├── pages/components
├── one shared runtime-status data source
├── operator-triggered actions
├── no raw sockets
└── no independent duplicate polling loops

Flask API
├── /api/runtime/services
├── /api/runtime/health
├── /api/runtime/discovery
├── existing domain APIs
└── explicit write endpoints with confirmation/policy checks

Python RuntimeManager
├── passive listeners
│   ├── sACN
│   └── Art-Net
├── DiscoveryCoordinator
│   ├── ARP/ping
│   ├── ArtPoll
│   └── vendor enrichment
├── BLE radio owner
├── device adapters
├── scheduler/bounded workers
├── lifecycle and clean shutdown
└── diagnostics snapshots
```

## 4. Delivery strategy

Use small, serial integration branches for the safety baseline, then one architecture branch per milestone. Do not combine migrations, OS-command safety, scanner behavior, Electron deletion, and packaging into one PR.

Recommended branch order:

1. `fix/<agent>/dead-root-migrations` — restore/recreate if the reviewed branch was deleted.
2. `fix/<agent>/network-route-safety` — complete and rebase active safety work.
3. `fix/<agent>/scanner-sweep-interface` — resolve review findings and rebase.
4. `feat/<agent>/preflight-doctor` — resolve review findings and rebase.
5. `docs/hermes/browser-canonical-runtime`.
6. `feat/hermes/runtime-manager-foundation`.
7. `fix/hermes/single-flight-discovery`.
8. `refactor/hermes/python-protocol-ownership`.
9. `feat/hermes/runtime-diagnostics`.
10. `test/hermes/ci-quality-gates`.
11. `refactor/hermes/backend-blueprints`.
12. `feat/hermes/electron-thin-shell`.
13. `feat/hermes/windows-packaging`.

Every branch must use an isolated worktree and an active record under `docs/coordination/active/`. Reserve exact paths before editing. Update the active record with commands/results, then move it to `docs/coordination/completed/` at handoff.

---

# Phase 0 — Establish a reproducible baseline

### Task 0.1: Create execution worktree and coordination record

**Objective:** Start implementation without colliding with Claude or existing active work.

**Files:**
- Create: `docs/coordination/active/hermes--runtime-architecture.md`

**Steps:**
1. Fetch and prune remote refs.
2. Read `AGENTS.md`, `docs/coordination/README.md`, and every current active record.
3. Create a dedicated branch/worktree from current `origin/main`.
4. Reserve only the first milestone's files.
5. Record baseline commit, branch, worktree, owner, scope, dependencies, and exclusions.
6. Commit and push the coordination record before code changes.

**Verification:** Remote branch exists; active record is readable from the remote branch; no reserved paths overlap another active task.

### Task 0.2: Record baseline quality evidence

**Objective:** Capture a reproducible starting point before refactoring.

**Files:**
- Create: `docs/architecture/runtime-baseline.md`

**Commands:**

```powershell
# From repository root on Windows
.\.venv\Scripts\python.exe -m pytest -q backend\tests
npm --prefix app test
npm --prefix app run build
```

```bash
# Linux reviewer equivalent
./.venv/bin/python -m pytest -q backend/tests
npm --prefix app test
npm --prefix app run build
```

**Steps:**
1. Run the canonical root-level backend command.
2. If subprocess tests fail because of cwd/import assumptions, preserve the failure output.
3. Run from `backend/` only as comparison evidence, not as a way to hide the root failure.
4. Run frontend tests and production build.
5. Record exact pass/fail counts, duration, commit, OS, Python, Node, and npm versions.
6. Record idle service/thread/socket/process counts in browser mode and Electron mode.

**Acceptance:** The baseline document distinguishes Linux software verification from Windows and actual-hardware verification.

### Task 0.3: Fix checkout-dependent test invocation

**Objective:** Make the documented test command pass from any clean clone or worktree.

**Likely files:**
- Modify: the BLE subprocess tests under `backend/tests/`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

**TDD steps:**
1. Add or tighten a test that launches the BLE child process from a non-repository cwd.
2. Run it and confirm the import/path failure.
3. Make the subprocess invoke a module/package using an explicit project path rather than an ambient cwd.
4. Run the focused test from repository root.
5. Run the complete backend suite from repository root.
6. Commit the test fix separately from architecture work.

**Acceptance:** The root-level command passes from the main checkout and a detached worktree.

---

# Phase 1 — Integrate existing safety work serially

### Task 1.1: Integrate dead-root-migrations cleanup

**Objective:** Remove the misleading obsolete migration history while preserving the live `backend/migrations/` chain.

**Steps:**
1. Locate the reviewed commit/branch; recreate it from review evidence if its remote branch was deleted.
2. Rebase onto current `origin/main`.
3. Strengthen the documentation regression test so the ambiguous root-level migration instruction cannot return.
4. Apply the live Alembic chain to a disposable MySQL database.
5. Verify one migration head and zero model/schema differences.
6. Label this database/software verification, not actual-gear evidence.
7. Merge independently before rebasing later branches.

**Never:** Run schema changes against Anthony's real database during this task.

### Task 1.2: Complete network-route command safety

**Objective:** Prevent unsafe command construction or overly broad adapter mutations.

**Likely files:**
- Modify: `backend/app/network_routes.py`
- Test: network-route tests under `backend/tests/`
- Update: `docs/coordination/active/claude--pr2-network-route-safety.md`

**Steps:**
1. Retrieve the active handoff; do not duplicate Claude's reserved work.
2. Rebase after migration cleanup.
3. Add failing tests for shell metacharacters, newline injection, malformed adapter identifiers, invalid CIDR/mask/gateway, and broad subnet PATCH requests.
4. Replace shell-string construction with argument-vector subprocess execution wherever possible.
5. Allowlist command/action shapes and validate all operator-controlled values.
6. Make failure responses specific but free of secrets.
7. Run focused tests, full backend tests, then Windows dry-run/bench verification.
8. Independently review before integration.

**Acceptance:** No request-controlled value can become PowerShell syntax; network writes remain explicit and scoped.

### Task 1.3: Finish scanner interface/sweep corrections

**Objective:** Make multi-interface discovery predictable and safe before introducing the coordinator.

**Likely files:**
- Modify: `backend/app/scanner.py`
- Test: `backend/tests/test_scanner_discovery.py`
- Test: `backend/tests/test_scanner_keepalive.py`

**Required regression shape:** A wide interface is reduced to the intended bounded sweep target, the first interface fails, and a later interface succeeds.

**Steps:**
1. Compare current branch against the formal review findings.
2. Write the production-shaped fan-out regression test.
3. Verify failure before implementation.
4. Correct API validation and interface fan-out behavior.
5. Add a safe desktop SQLite migration if the branch changes persisted scanner metadata.
6. Run focused scanner tests and full backend suite.
7. Perform Windows interface-selection verification without changing adapter settings.

### Task 1.4: Finish the preflight doctor

**Objective:** Fail closed before startup when dependencies or ports are unhealthy.

**Likely files:**
- Modify: branch-specific doctor and launcher files
- Test: branch-specific doctor tests
- Modify: `start.ps1` if owned by this branch

**Required cases:**
- Foreign process owns port 5000.
- Existing Five12 backend owns port 5000.
- Doctor throws before returning a valid result.
- Required Python/module/tool is absent.
- Browser mode and desktop mode report the selected runtime clearly.

**Acceptance:** A false-green result cannot cause another backend to launch; doctor exceptions fail closed with a useful operator message.

---

# Phase 2 — Make browser mode canonical and Electron explicitly experimental

### Task 2.1: Add an architecture decision record

**Objective:** Prevent future contributors from reintroducing two protocol engines.

**Files:**
- Create: `docs/architecture/adr-001-browser-canonical-python-runtime.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

**ADR decision:**
- Browser/Vite is canonical for daily development.
- Electron is an experimental shell until the packaging milestone.
- Python exclusively owns protocols/hardware.
- Electron-specific protocol logic is deprecated and receives no new features.

**Verification:** A new contributor can identify the canonical start/test commands and ownership boundaries without reading source.

### Task 2.2: Display runtime mode in the UI

**Objective:** Make it impossible to confuse browser and Electron evidence.

**Likely files:**
- Modify: `app/src/App.jsx`
- Create: `app/src/components/RuntimeModeBadge.jsx`
- Test: `app/src/components/RuntimeModeBadge.test.jsx`
- Modify: `electron/preload.js`

**TDD steps:**
1. Test browser mode renders `Development · Browser`.
2. Test Electron mode renders `Experimental · Desktop` until packaging release.
3. Expose only a small immutable runtime descriptor through preload.
4. Render a compact badge in Settings/About, not a distracting production banner.
5. Run Vitest and production build.

**Acceptance:** Screenshots and bug reports clearly identify runtime mode.

---

# Phase 3 — Introduce the Python runtime manager

### Task 3.1: Define service lifecycle and status contracts

**Objective:** Establish one vocabulary before moving services.

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/contracts.py`
- Test: `backend/tests/test_runtime_contracts.py`

**Minimum service status fields:**

```text
name
category: passive | discovery | radio | adapter
state: stopped | starting | running | stopping | degraded | failed
started_at
last_success_at
last_error_at
last_error_code
last_error_summary
work_count
interface
restart_count
```

**Rules:**
- No credentials, command text, BLE payloads, client names, or private show data in snapshots.
- `start()` and `stop()` are idempotent.
- Status serialization is deterministic.

**TDD cycle:** Write serialization/redaction/idempotency tests, verify failure, implement minimum contract, rerun focused tests, commit.

### Task 3.2: Build `RuntimeManager`

**Objective:** Register, start, stop, and inspect one instance of each service.

**Files:**
- Create: `backend/app/services/runtime_manager.py`
- Test: `backend/tests/test_runtime_manager.py`

**Required tests:**
- Duplicate service name is rejected.
- Starting an already-running service is harmless.
- Stopping an already-stopped service is harmless.
- One service failure does not prevent others from reporting status.
- Shutdown occurs in reverse dependency order.
- Stop timeout marks a service degraded/failed rather than hanging process exit.
- Status snapshots are thread-safe.

**Implementation constraint:** Do not introduce a general plugin framework. Build only the lifecycle needed by current services.

### Task 3.3: Connect manager to Flask lifecycle

**Objective:** Start enabled services once and stop them cleanly.

**Likely files:**
- Modify: `backend/app/__init__.py`
- Modify: `backend/config.py`
- Test: `backend/tests/test_runtime_startup.py`

**Steps:**
1. Test app creation does not create duplicate managers.
2. Test test configuration starts no real network/BLE service.
3. Test desktop configuration selects explicit enabled services.
4. Register bounded shutdown hooks.
5. Preserve existing feature flags.
6. Run full backend suite.

---

# Phase 4 — Make discovery single-flight and bounded

### Task 4.1: Implement `DiscoveryCoordinator`

**Objective:** Route scheduled and manual sweeps through one owner.

**Files:**
- Create: `backend/app/services/discovery_coordinator.py`
- Modify: `backend/app/scanner.py`
- Test: `backend/tests/test_discovery_coordinator.py`

**Behavior:**
- At most one full discovery sweep runs at once.
- A concurrent request returns the current `scan_id` and `already_running` status.
- At most one follow-up scan may be queued; repeated clicks do not create more work.
- Scheduled and manual scans share the same gate.
- Keep-alive work yields or pauses during a full sweep.
- Worker count, per-host timeout, total sweep deadline, and subprocess concurrency are bounded.
- Cancellation/shutdown stops launching new probes and waits only up to a bounded deadline.

**Required tests:**
- Ten simultaneous manual requests start one sweep.
- Scheduled request racing manual request starts one sweep.
- Repeated requests queue no more than one follow-up.
- Exception releases the single-flight gate.
- Shutdown during scan exits within deadline.
- Wide network scope is bounded according to explicit policy.

### Task 4.2: Version the discovery API response

**Objective:** Give the UI stable scan state instead of relying on button timing.

**Likely files:**
- Modify: `backend/app/network_routes.py`
- Modify: `app/src/pages/NetworkMonitor.jsx`
- Test: backend route test
- Test: `app/src/pages/NetworkMonitor.test.jsx`

**Response shape:**

```json
{
  "scanId": "opaque-id",
  "state": "running",
  "started": false,
  "reason": "already_running",
  "queuedFollowUp": false
}
```

**Acceptance:** Repeated Scan clicks do not increase thread/process count; UI reports the existing scan instead of pretending a new one started.

---

# Phase 5 — Consolidate passive protocol ownership in Python

### Task 5.1: Inventory Electron IPC consumers

**Objective:** Prove which renderer paths still depend on Electron networking before deletion.

**Files:**
- Create: `docs/architecture/electron-network-ipc-inventory.md`

**Steps:**
1. Enumerate every channel exposed by `electron/preload.js`.
2. Find every React consumer.
3. Map each IPC result to its Python/API equivalent.
4. Mark missing backend parity explicitly.
5. Do not delete Electron code until every consumer is migrated and tested.

### Task 5.2: Adapt Python sACN listener to the runtime manager

**Objective:** Ensure one receive socket and observable lifecycle.

**Likely files:**
- Modify: `backend/app/sacn_listener.py`
- Modify: `backend/app/services/runtime_manager.py`
- Test: `backend/tests/test_sacn_parse.py`
- Create: `backend/tests/test_sacn_lifecycle.py`

**Required tests:**
- Repeated start opens one socket.
- Repeated stop is harmless.
- Bind failure reports degraded/failed status.
- Selected interface/multicast membership is explicit.
- Packet parser failure does not kill listener loop.
- Shutdown closes socket and thread.

### Task 5.3: Migrate Art-Net monitoring to Python

**Objective:** Provide backend parity for renderer-visible Art-Net data.

**Likely files:**
- Create or modify a Python Art-Net listener service under `backend/app/services/`
- Modify: `backend/app/network_routes.py`
- Test: new parser/lifecycle tests under `backend/tests/`
- Modify: `app/src/pages/NetworkMonitor.jsx`

**Safety:** Art-Net listening is passive; ArtPoll transmission remains active discovery and must use `DiscoveryCoordinator`.

### Task 5.4: Remove Electron protocol engine

**Objective:** Make Electron a thin shell after parity is proven.

**Files:**
- Modify: `electron/main.js`
- Modify: `electron/preload.js`
- Modify: `app/src/pages/NetworkMonitor.jsx`
- Test: Electron smoke-test script or documented automated harness

**Deletion gate:**
- Browser and Electron use the same Flask endpoints.
- Python lifecycle tests pass.
- React tests pass.
- UDP port ownership inspection shows one owner per listener.
- Windows browser and Electron smoke tests report identical monitored data.

**Acceptance:** No `dgram` protocol socket or Art-Net/sACN parser remains in Electron.

---

# Phase 6 — Replace polling sprawl with one status data source

### Task 6.1: Add runtime snapshot API

**Objective:** Return one coherent, cached health snapshot.

**Files:**
- Create: `backend/app/runtime_routes.py`
- Modify: `backend/app/__init__.py`
- Test: `backend/tests/test_runtime_routes.py`

**Endpoints:**
- `GET /api/runtime/health` — lightweight overall health.
- `GET /api/runtime/services` — redacted service snapshots.
- `POST /api/runtime/services/<name>/restart` — only for allowlisted non-write services, with explicit operator action.

**Acceptance:** Snapshot reads do not trigger scans or device connections.

### Task 6.2: Centralize frontend polling

**Objective:** Replace page-local intervals with one cancellable runtime-status hook.

**Files:**
- Create: `app/src/hooks/useRuntimeStatus.js`
- Test: `app/src/hooks/useRuntimeStatus.test.jsx`
- Modify: `app/src/pages/NetworkMonitor.jsx`

**Required tests:**
- One interval regardless of component rerenders.
- Request is aborted on unmount.
- No overlapping HTTP request when the previous poll is slow.
- Backoff occurs on repeated failure.
- Page visibility pause/resume is safe.
- Stale data is visibly marked rather than cleared.

**YAGNI:** Start with HTTP snapshots. Do not add WebSockets/SSE until measured polling load demonstrates need.

---

# Phase 7 — Add operator-facing diagnostics

### Task 7.1: Build diagnostics page

**Objective:** Let Anthony see exactly what Five12 is doing.

**Files:**
- Create: `app/src/pages/Diagnostics.jsx`
- Create: `app/src/components/ServiceStatusCard.jsx`
- Modify: `app/src/App.jsx`
- Test: corresponding Vitest files

**Display:**
- Service state and category.
- Interface/address family where safe.
- Start time, last success, last error summary.
- Work/packet/scan counters.
- Whether scan is running or queued.
- Runtime mode and application version.
- Backend process uptime.

**Never display:** credentials, raw command lines, BLE secrets, private show data, or unredacted stack traces.

### Task 7.2: Export sanitized diagnostics

**Objective:** Produce a support bundle suitable for Claude/Hermes review.

**Files:**
- Create backend endpoint/helper for sanitized JSON export.
- Add UI download action.
- Test redaction and schema stability.

**Acceptance:** Automated tests seed secrets into internal errors and prove none appear in the exported bundle.

---

# Phase 8 — Add professional quality gates

### Task 8.1: Add continuous integration

**Objective:** Prevent untested branches and broken builds.

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify dependency/config files only if required

**Jobs:**
1. Backend tests from repository root.
2. Frontend Vitest suite.
3. Frontend production build.
4. Migration layout/head verification using disposable database service where practical.
5. Secret scanning and dependency audit with reviewed failure policy.

**Acceptance:** Workflow runs on pull requests and protected branches; commands match local documented commands.

### Task 8.2: Add runtime leak/regression tests

**Objective:** Detect the slowdown Anthony is worried about.

**Files:**
- Create: `backend/tests/test_runtime_resource_bounds.py`

**Tests:**
- Repeated start/stop does not grow threads.
- Repeated Scan requests do not grow workers/subprocesses beyond configured bound.
- Service status polling does not launch work.
- Shutdown leaves no managed service thread alive.
- Listener restart releases/rebinds its socket correctly.

**Performance method:** Measure baseline first. Set budgets from observed healthy behavior plus justified headroom; do not invent arbitrary production limits.

### Task 8.3: Expand critical frontend coverage

**Objective:** Protect operator workflows before desktop packaging.

**Priority coverage:**
- Patch editing and DMX conflict behavior.
- Import/export error handling.
- Network monitor stale/offline states.
- Discovery single-flight UI.
- Diagnostics redaction/display.
- Runtime-mode badge.

---

# Phase 9 — Split backend routes by domain

### Task 9.1: Add blueprint characterization tests

**Objective:** Freeze API behavior before moving route definitions.

**Files:**
- Create characterization tests for shows, patch sheets, fixtures, labels, imports/exports, network monitor, network writes, and runtime APIs.

**Acceptance:** Status codes and JSON key conventions are captured without depending on blueprint implementation details.

### Task 9.2: Move routes incrementally

**Target files:**
- `backend/app/show_routes.py`
- `backend/app/patch_routes.py`
- `backend/app/fixture_routes.py`
- `backend/app/label_routes.py`
- `backend/app/import_export_routes.py`
- `backend/app/network_routes.py`
- `backend/app/runtime_routes.py`

Move one domain per commit. Run focused characterization tests and full suite after each move. Do not change endpoint behavior and file organization in the same commit.

---

# Phase 10 — Build the thin Electron shell

### Task 10.1: Define desktop process contract

**Objective:** Specify startup, readiness, shutdown, crash, and data-directory behavior.

**Files:**
- Create: `docs/architecture/desktop-process-contract.md`

**Required behavior:**
- Electron selects a free loopback port or uses a deliberate fixed port with ownership proof.
- Backend binds loopback only.
- Electron waits for a versioned readiness endpoint, not a blind sleep.
- Backend child identity is tracked.
- Normal window close triggers bounded graceful shutdown.
- Crash restart is bounded and visible; no infinite restart loop.
- Existing foreign service on the port fails closed.
- Logs and data use OS-appropriate application directories.

### Task 10.2: Remove hard-coded Python path

**Objective:** Run a packaged backend artifact rather than Anthony's personal interpreter path.

**Likely files:**
- Modify: `electron/main.js`
- Modify: `electron/package.json`
- Add backend packaging specification/script after a time-boxed packaging spike

**Spike decision:** Compare PyInstaller and an equivalent supported bundler using startup time, package size, native dependency behavior, Bleak/Windows support, and reproducibility. Record the decision in an ADR before adoption.

### Task 10.3: Harden Electron boundaries

**Objective:** Keep the shell narrow and safe.

**Checks:**
- `contextIsolation: true`.
- `nodeIntegration: false`.
- Minimal allowlisted preload API.
- Navigation and new-window allowlist.
- External links opened safely.
- No remote content receives privileged IPC.
- Local API uses a per-launch capability token if threat-model review says loopback origin alone is insufficient.

### Task 10.4: Add desktop smoke tests

**Cases:**
- Clean launch.
- Backend readiness.
- Main navigation/API request.
- Second launch behavior.
- Foreign port owner.
- Backend crash.
- Window close and process cleanup.
- Application data preserved across upgrade.

---

# Phase 11 — Packaging, migration safety, and field verification

### Task 11.1: Prove data backup and restore

**Objective:** Protect show, patch, fixture, label, device, and configuration data.

**Steps:**
1. Document authoritative data locations.
2. Implement backup before schema upgrade.
3. Restore into a disposable installation.
4. Compare row counts and representative records.
5. Simulate failed migration and prove rollback/recovery instructions.

### Task 11.2: Build unsigned internal installer

**Objective:** Produce a reproducible internal artifact for Anthony's ThinkPad.

**Verification:** Clean Windows account/VM install, no preinstalled Python dependency, app starts offline, backend binds loopback, browser and desktop show equivalent data, uninstall preserves or explicitly offers to preserve user data.

### Task 11.3: Run staged hardware bench matrix

**Objective:** Separate software verification from actual-gear evidence.

**Matrix:**
- No network/BLE hardware connected.
- One wired interface.
- Multiple active interfaces/VPN/Tailscale.
- sACN source present/absent/malformed packet.
- Art-Net node present/absent.
- BLE adapter absent/disabled/busy.
- Simulator versus authorized BLE hardware.
- Npcap/admin available and unavailable.
- Sleep/resume and network-interface change.
- Electron close/reopen and abnormal termination.

**Safety:** Device-write tests use dummy/simulator equipment first. No CRMX link, NIC mutation, reboot, or production-device write occurs without Anthony's explicit bench authorization.

### Task 11.4: Release-readiness gate

Five12 is ready for a limited desktop beta only when:

- CI is green from a clean clone.
- Browser and Electron call the same Python APIs.
- Electron contains no protocol engine.
- One service instance owns each socket/radio.
- Discovery is single-flight and bounded.
- Runtime diagnostics show service health and sanitized errors.
- Clean shutdown leaves no backend, worker, or listener process behind.
- Installer requires no personal Python path.
- Backup/restore and migration failure recovery are proven.
- Windows software verification and approved actual-gear verification are recorded separately.
- Security review finds no command injection, broad network-write, secret leakage, or remote-binding regression.

---

## 5. Explicit pitfalls and mitigations

| Pitfall | Mitigation |
|---|---|
| Scanner button/scheduler creates overlapping sweeps | One `DiscoveryCoordinator`; concurrency and queue tests |
| Ping subprocess burst on wide networks | Bounded targets, worker pool, timeout, total deadline |
| Electron and Python bind the same UDP ports | Python-only protocol ownership; socket-owner verification |
| sACN multicast joins wrong interface | Explicit interface selection and lifecycle tests on Windows |
| Art-Net broadcast unintentionally crosses interfaces | Explicit egress selection; active discovery classification |
| BLE radio gets multiple owners | Preserve OS lock and one event-loop owner |
| Background exception is swallowed | Specific exceptions, structured status, last-error reporting |
| Status UI itself causes load | Cached snapshots; one non-overlapping poller |
| Shutdown leaves orphan process/thread | Reverse-order bounded shutdown and process-identity tracking |
| Test passes only from one cwd | Root-level clean-worktree CI command |
| Migration damages Anthony's data | Disposable DB, backup/restore proof, fail-closed upgrade |
| Desktop works only on Anthony's machine | Clean Windows user/VM installer test |
| Diagnostics leak secrets or production data | Schema allowlist and adversarial redaction tests |
| Refactor changes API accidentally | Characterization tests before route moves |
| New abstraction becomes larger than app | YAGNI: contract, manager, coordinator only; no plugin marketplace |
| Feature branches drift while integration proceeds | Serial rebase/integration with active records and explicit handoffs |

## 6. Recommended starting slice for today

Do only this slice before the first review checkpoint:

1. Create the isolated execution branch/worktree and coordination record.
2. Capture the exact backend/frontend/build baseline.
3. Fix the checkout-dependent backend test command if still failing.
4. Write and merge the browser-canonical/Python-owned-runtime ADR.
5. Inventory Electron network IPC and React consumers.
6. Produce a short measured before-state: threads, child processes, sockets, intervals, and enabled services in browser versus Electron mode.

Do **not** begin deleting Electron networking or moving scanner code until that evidence and dependency map are reviewed.

## 7. Review and execution checkpoints

- **Checkpoint A:** Baseline, ADR, IPC inventory, and branch-integration order approved.
- **Checkpoint B:** Safety branches merged; complete suite/build green.
- **Checkpoint C:** Runtime manager and single-flight discovery independently reviewed.
- **Checkpoint D:** Python protocol parity proven; Electron protocol engine removable.
- **Checkpoint E:** Diagnostics and CI green; measured runtime bounds accepted.
- **Checkpoint F:** Thin Electron shell and installer validated on clean Windows environment.
- **Checkpoint G:** Approved hardware bench matrix complete; limited beta decision.

At every checkpoint, update the active record with exact commands and results. A generated file, passing simulation, or Linux check must never be mislabeled as actual-hardware verification.

---

# 8. Claude Code + Hermes joint execution protocol

## 8.1 Collaboration principle

Claude and Hermes should not both edit the same implementation branch. For each milestone:

1. One agent is the **implementer** and owns the isolated branch/workspace.
2. The other agent is the **independent reviewer** and does not modify the implementation branch during the initial review.
3. The implementer responds to findings on the same feature branch.
4. The reviewer reruns focused and canonical checks before approval.
5. Integration occurs serially through `main`; dependent branches rebase only after their prerequisite merges.

This avoids two agents producing overlapping versions of the same fix while still using both agents' strengths.

## 8.2 Proposed responsibilities

### Anthony — product owner and hardware authority

- Approves changes to visible workflow and product scope.
- Authorizes any real NIC, BLE, CRMX, reboot, or device-write test.
- Decides whether a usability tradeoff is acceptable.
- Receives checkpoint summaries in plain English.
- Does not need to mediate routine branch mechanics unless the agents disagree on product behavior or safety.

### Claude Code — primary bounded implementation lane

Claude should initially own work where it already has branch context or where a contained code change can be implemented and tested in one fresh cloud branch:

- Existing dead-migration cleanup reconstruction/integration.
- Existing network-route safety corrections.
- Existing scanner interface/sweep corrections.
- Existing preflight-doctor corrections.
- React runtime-mode badge and later diagnostics components after the API contract is frozen.
- Electron thin-shell and Windows packaging implementation after Python protocol parity is proven.

Claude cloud requirements:

- Start from freshly fetched `origin/main` unless a task explicitly names a reviewed feature branch.
- Create/update `docs/coordination/active/claude--<slug>.md` before application edits.
- Commit and push before the cloud session ends.
- Return branch name, full commit SHA, changed paths, exact tests/results, evidence level, skipped checks, and risks.
- Never claim Windows or actual-gear verification unless it was actually run and the device/OS context is recorded.

### Hermes — architecture, sequencing, implementation on separate lanes, and independent verification

Hermes should own:

- Overall dependency graph and integration order.
- Baseline capture and before/after runtime measurements.
- Browser-canonical/Python-ownership architecture decision.
- Electron IPC/network dependency inventory.
- Runtime contracts and `RuntimeManager` implementation, unless reassigned after Claude's review.
- CI/resource-bound tests on a separate branch.
- Independent review of Claude's branches, including diff inspection and rerunning canonical checks.
- Reconciliation of cross-branch API contracts.
- Plain-English checkpoint summaries for Anthony.

Hermes requirements:

- Use persistent isolated worktrees.
- Reserve exact paths before editing.
- Never accept a Claude self-report without fetching the branch, inspecting the diff, and rerunning applicable checks.
- Push review artifacts under `docs/coordination/reviews/` and provide the remote branch/SHA so Claude can retrieve them.
- Keep Linux software verification separate from Windows and actual-hardware evidence.

## 8.3 Recommended owner/reviewer matrix

| Milestone | Implementer | Independent reviewer | Parallel? |
|---|---|---|---|
| Plan critique and dependency check | Claude | Hermes reconciles | No code |
| Reproducible baseline/test-path fix | Hermes | Claude | No |
| Dead migration cleanup | Claude | Hermes | Serial |
| Network-route safety | Claude | Hermes | Serial; collision-prone |
| Scanner interface corrections | Claude | Hermes | After preceding merge/rebase |
| Preflight doctor | Claude | Hermes | After preceding merge/rebase |
| Browser-canonical ADR | Hermes | Claude | May proceed only if reserved docs do not collide |
| Electron IPC inventory | Hermes | Claude | Read-only inventory can overlap; edits cannot |
| Runtime service contract | Hermes | Claude | No downstream implementation until approved |
| RuntimeManager and startup lifecycle | Hermes | Claude | No |
| DiscoveryCoordinator | Claude or Hermes by explicit assignment | Other agent | No |
| Python sACN/Art-Net ownership | One agent per service branch | Other agent | Only if files/contracts do not overlap |
| React status hook/diagnostics UI | Claude | Hermes | Yes, after API schema freezes |
| CI and resource-bound tests | Hermes | Claude | Yes if lockfiles/shared config are reserved |
| Backend route split | Claude | Hermes | One domain branch at a time |
| Electron thin shell/packaging | Claude | Hermes | After protocol engine removal gate |
| Windows and hardware matrix | Anthony-assisted implementer | Other agent reviews evidence | Staged, explicitly authorized |

The named owner is a default, not a permanent entitlement. Reassignment must be recorded in the active note before editing.

## 8.4 Contract-first parallelism

Parallel work is allowed only after a shared contract is written and approved. Example:

1. Hermes writes and tests the `/api/runtime/services` response schema.
2. Claude reviews the schema and records approval/findings.
3. Hermes owns backend implementation files.
4. Claude owns frontend hook/component files.
5. Neither agent changes the schema without updating both active records and obtaining a handoff.
6. Each branch runs its focused checks.
7. Backend merges first; frontend rebases and runs integration tests against the merged API.

Parallelism is prohibited for:

- `backend/app/models.py` and migrations.
- `backend/app/__init__.py` startup lifecycle.
- `backend/app/routes.py` or an API contract under active refactor.
- `electron/main.js` during protocol-engine removal.
- Dependency manifests and lockfiles.
- `AGENTS.md`, `CLAUDE.md`, and shared coordination rules.

## 8.5 Handoff format

Every implementation handoff must include:

```text
Task:
Owner:
Branch:
Base SHA:
Head SHA:
Changed paths:
API/schema/migration/dependency changes:
Commands run:
Exact results:
Evidence level: simulated | software verification | bench-tested | verified on actual gear
Known risks:
Skipped checks:
Review requested from:
Recommended next action:
```

Every review must use:

```text
Critical — unsafe/data-loss/security/release blocker
Warning — correctness or maintainability issue that should block integration
Suggestion — worthwhile improvement that does not block integration
Looks Good — verified strengths and checks rerun
Verdict — approve | approve with non-blocking suggestions | request changes
```

Review files belong under `docs/coordination/reviews/`. The reviewer must identify the exact reviewed commit SHA; reviewing an unpinned moving branch is not sufficient.

## 8.6 Disagreement and escalation

- Technical disagreement: each agent records evidence and a proposed experiment; use the smallest reproducible test to decide.
- Product/workflow disagreement: Anthony decides after receiving the concrete tradeoff in plain English.
- Safety disagreement: choose the fail-closed/read-only behavior until resolved.
- Hardware claim disagreement: downgrade the evidence label and rerun with the authorized device.
- Branch collision: both agents stop editing the shared path; the current reservation owner finishes or explicitly hands it off.

## 8.7 First joint cycle

1. Anthony sends this plan to Claude for a read-only critique.
2. Claude checks the plan against current `origin/main`, all active coordination records, and its unpublished/local branches.
3. Claude writes findings using Critical / Warning / Suggestion / Looks Good, without implementing code yet.
4. Claude identifies stale branch assumptions, missing dependencies, unsafe ordering, and path collisions.
5. Claude commits/pushes its critique or provides a branch/SHA that Hermes can fetch.
6. Hermes independently verifies the critique and updates the execution plan where warranted.
7. Hermes starts the baseline/test-path branch.
8. Claude starts only the first assigned safety branch whose prerequisites and reservations are clear.
9. Both agents exchange branch/SHA handoffs through Git, not pasted summaries alone.
10. Anthony receives one combined Checkpoint A report rather than two conflicting status messages.

## 8.8 Prompt Anthony can send to Claude

```text
Read the Five12 Runtime and Desktop Hardening Implementation Plan in full.

Before editing code, fetch current origin/main and read AGENTS.md,
docs/coordination/README.md, and every file under docs/coordination/active/.

For this first pass, act only as an independent plan reviewer. Do not implement
or change application code yet. Check the plan against the current repository,
your existing local/unpublished branches, and prior Hermes review findings.

Return findings under Critical / Warning / Suggestion / Looks Good. Specifically
check:
- dependency and merge order;
- branch names/availability and stale assumptions;
- file-reservation collisions;
- whether browser-canonical and Python-only protocol ownership are practical;
- RuntimeManager and DiscoveryCoordinator scope/YAGNI;
- Electron IPC migration and packaging ordering;
- missing Windows, database, security, frontend, and hardware verification;
- tasks that can safely run in parallel versus tasks that must remain serial.

For every finding, cite exact files, branches, or tests. End with a proposed
owner/reviewer split between Claude and Hermes. If you save the review in Git,
use docs/coordination/reviews/, commit it on a dedicated docs/claude/<slug>
branch, push it, and return the branch name and full commit SHA.

Do not claim a check passed unless you actually ran it. Label simulated,
software, Windows bench, and actual-hardware evidence separately. Do not expose
credentials or perform live network/BLE/device writes.
```
