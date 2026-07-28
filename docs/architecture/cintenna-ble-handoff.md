# Cintenna BLE — Handoff (read-only phase)

Branch `feat/cintenna-ble`, 29 commits, **not merged, not pushed**, as of 2026-07-27.

The read-only phase is complete and reviewed. It is deliberately parked before
merge pending hardware verification — see [Hardware gate](#hardware-gate).

Companion documents:

- Design: [`../superpowers/specs/2026-07-26-cintenna-ble-design.md`](../superpowers/specs/2026-07-26-cintenna-ble-design.md)
- Repo/architecture map: [`ble-integration-map.md`](ble-integration-map.md)
- Plan (13 tasks, full code): [`../superpowers/plans/2026-07-26-cintenna-ble-readonly.md`](../superpowers/plans/2026-07-26-cintenna-ble-readonly.md)

## What shipped

A **Cintennas** tab on the Devices page. A daemon thread owns a `bleak` event
loop and a device registry; `CintennaAdapter` reads that registry synchronously
so the existing tab strip works unchanged; `/api/ble/*` serves the roster and
connected status reads behind `ENABLE_BLE_TOOLS`.

Verify with:

```
cd backend && python -m pytest      # 286 passed
cd app     && npm run test          # 20 passed
cd app     && npm run build         # succeeds
```

Note the interpreter split recorded in the integration map: tests run on the
global Python 3.14, the app runs on `AppData\...\Python312`, and `bleak` is
installed **only** on the app runtime. `pytest` is not on PATH — use
`python -m pytest`.

## Release blockers — all verified holding

Confirmed across the whole branch by the final review, and each gated by a test
that fails if violated:

- No write path anywhere. No `write_gatt_char`, no mutating `/api/ble` route, no
  `command_service.py`, no UI control that writes to a radio.
- No linking-key handling, firmware update, RDM, BLE DMX streaming, and no read
  of the opaque blob characteristic `10351003`.
- Fully removable: with `FIVE12_BLE_TOOLS` unset no thread starts, the routes do
  not exist, and Patch/Labels/Network are untouched.
- Nothing claims a radio is "linked" — an ATT acknowledgement is not evidence of
  RF association. No field named `linked` exists.
- Nothing claims a "Cintenna 2" from radio-platform evidence alone.
- RSSI is never presented as distance.

**If you add the write phase, these are the properties to keep.** The strongest
guards are `test_ble_constants.py` (no write allowlist), `test_ble_routes.py`
(no mutating route in `url_map`), `test_ble_gatt_client.py` (production
`BleakClientAdapter` exposes no write method), and `CintennaPanel.test.jsx`
(no Link/Unlink/Set-mode/Apply control renders).

## Hardware gate

**Partially met as of 2026-07-27.** A real Cintenna was discovered by the passive
scan and returned a connected status read. The remaining steps — the Toolbox
conflict check in particular — are still unrun. Everything else remains verified
only against fakes, sim fixtures, and captured byte values.

- [x] Passive scan finds the device without connecting, CRMX Toolbox closed
- [x] Advertised name, RSSI, service UUID, and manufacturer payload all appear
- [x] Connect and read battery, firmware, and the RX snapshot
- [ ] **Open Toolbox, attempt a snapshot, confirm the error names Toolbox.**
      This is the most valuable check: it is the most common real failure, and
      the detection is English-substring matching (see deferred minors below)
- [ ] Close Toolbox, reconnect successfully
- [ ] Unset `FIVE12_BLE_TOOLS`, confirm Patch/Labels/Network/Devices still work

Run the app with `FIVE12_BLE_TOOLS=1`; add `FIVE12_DEVICE_SIM=1` for two
simulated radios without hardware.

## Deferred minors — triaged by the final whole-branch review

Recorded here because the working ledger (`.superpowers/sdd/progress.md`) is
gitignored scratch and will not survive a clean.

**Accepted, ship as-is:**

| Item | Why it is fine |
|---|---|
| `capabilities()` hardcodes `bleToolsEnabled: True` | The route only exists when the gate is on — a tautology, not a lie |
| `evidence` list looks redundant with `platform != None` | Not redundant in the composed system; `scanner.py` adds `service-uuid` independently and the UI renders it as badges |
| sim shares one `evidence` list between both devices | Latent only; nothing mutates it in place |
| PID-offset in the lock file has no pytest coverage | The PID is diagnostics-only and never decides ownership; ownership itself has real subprocess tests including force-kill recovery |
| `get_scan_service` caches the not-owner service forever | A worker that loses the adapter race never retries. Fixing it means a re-acquire poll on the most safety-critical component; gunicorn worker recycling mitigates |
| `build_sim_snapshot` populates no warnings / per-field error | Shape parity with the real path is actively asserted, and sim fixtures cover all 11 UUIDs |
| `signalBars` returns 1 for literal `NaN` | `NaN` cannot arrive through JSON; `null` is handled correctly |
| `fetchBleSnapshot` rejects with a plain object, not an `Error` | Its sole consumer reads `.message`; the shape is tested. **Do not add `instanceof Error` checks against it** |

**Known-fragile, worth revisiting when evidence exists:**

- **Toolbox-conflict detection matches English substrings** (`'in use'`, `'access'`,
  `'busy'`) in `connection_manager.py`. On a non-English Windows locale a real
  Toolbox conflict degrades to the generic "device out of range" guidance. It
  never crashes and never takes a wrong action — it just gives worse advice. A
  real fix needs HRESULT evidence from non-English hardware that does not exist
  yet. **The hardware gate's Toolbox step is where this would show up.**
- **`READABLE_UUIDS` is not load-bearing.** Nothing outside tests imports it;
  `gatt_client._FIELDS` is the de facto allowlist. The chain holds today only
  transitively. Before the write phase, add a direct assertion that every UUID
  in `_FIELDS` is a member of `READABLE_UUIDS`, so the constant actually
  enforces something.
- **Sim polling responsibility is split.** `ble_routes.list_devices` calls
  `poll_sim()`; `CintennaAdapter` does not. Under `?sim=1` the Devices tab card
  reads "not scanning · 0 nearby" until something first hits
  `/api/ble/devices?sim=1`. Cosmetic and sim-only.
- **`asyncio` safety assumes sync workers.** Snapshots submit onto the scan
  service's loop, which is only safe because the app never runs under a threaded
  or async worker. True today (`Procfile` uses default sync gunicorn workers).
  Switching to gevent/eventlet/uvicorn would silently break it — there is a
  comment in `ble_routes.py` recording this.

**Dead code left in place deliberately** (harmless, likely used by the write
phase): `errors.NotOwner` and `errors.CharacteristicMissing` are never raised;
`constants.CONFIG_SERVICE` duplicates `TIMOTWO_SERVICE_UUID`; `Registry.count()`
is unused; `bleApi.fetchBleCapabilities` is exported and tested but uncalled.

## Frontend dependency security

`fix/frontend-dependency-vulns` (commit `c8be6db`) is a **separate branch off
`main`**, merged into this one. It has no hardware dependency and can merge
independently — it does not need to wait for the BLE feature.

`npm audit --omit=dev` reports **2 high**, both the same advisory: React Router
**RSC-mode** CSRF bypass, `>=7.12.0 <8.3.0`, no forward fix in v7.

**Do not run `npm audit fix --force` to clear them.** npm's suggested
remediation is a downgrade to `react-router-dom@7.11.0`, which reintroduces
roughly thirteen CVEs — open redirect via `<Link>`, `deserializeErrors`
arbitrary constructor injection, the DoS pair, the XSS set. The advisory is
RSC-only and this app is a plain SPA with no RSC, no server, and no actions, so
it is structurally unreachable. Re-check when 8.3.0 or a v7 backport lands.

Note the `overrides` entry pinning `dompurify` in `app/package.json`. It is
load-bearing: jspdf declares dompurify as an *optional* dependency at `^3.3.1`,
which the vulnerable 3.4.3 satisfies, so a lock-only bump silently reverts on
any fresh clone or lock regeneration. Do not remove the override.

## Next phase

Designed, 2026-07-27, once the scan-and-read half of the hardware gate passed:
[`../superpowers/specs/2026-07-27-cintenna-ble-write-phase-design.md`](../superpowers/specs/2026-07-27-cintenna-ble-write-phase-design.md).

Implementation plan:
[`../superpowers/plans/2026-07-27-cintenna-ble-write-phase.md`](../superpowers/plans/2026-07-27-cintenna-ble-write-phase.md).
Hardware acceptance for it:
[`cintenna-ble-write-acceptance.md`](cintenna-ble-write-acceptance.md).

The write phase keeps every release blocker from the read-only phase except
"no write path", which becomes "no write path outside the four-command
allowlist". The four guard tests were inverted rather than deleted — see the
plan's Tasks 2, 4, 9 and 12.

It deliberately narrows the original tasks 10–18 to **four commands** —
`set_mode_rx`, `set_mode_tx`, `link`, `unlink` — behind a second gate,
`FIVE12_BLE_WRITE`. The other four config writes stay deferred; the policy table
is data, so each is one row plus its own acceptance run when wanted.

Two numbers are still deliberately unset in that design because they need the
radio: reboot timing after a mode write, and whether device identity survives
the reboot. They are recorded as open questions, not guessed.

Protocol source of truth for that work is the private KB:
`10-Lighting/References/LumenRadio/timotwo-ble-discovery-and-gatt.md` and
`five12-cintenna-ble-implementation-plan.md`.

---

# Write phase — mode toggle, TX Link, RX Unlink

**Code complete and reviewed as of 2026-07-28. Not merged, not pushed.**
Blocked only on the hardware acceptance run —
[`cintenna-ble-write-acceptance.md`](cintenna-ble-write-acceptance.md).

Design: [`../superpowers/specs/2026-07-27-cintenna-ble-write-phase-design.md`](../superpowers/specs/2026-07-27-cintenna-ble-write-phase-design.md)
Plan: [`../superpowers/plans/2026-07-27-cintenna-ble-write-phase.md`](../superpowers/plans/2026-07-27-cintenna-ble-write-phase.md)

## What shipped

Four commands, and only four: `set_mode_rx`, `set_mode_tx`, `link`, `unlink`.
They live in one frozen table in `five12_ble/command_service.py`, which is the
entire write surface. A second gate, `FIVE12_BLE_WRITE`, must be set on top of
`FIVE12_BLE_TOOLS`; with it unset the app is the read-only build, with no
mutating route in the URL map and no write control in the UI.

Verify with:

```
cd backend && python -m pytest      # 368 passed (+5, see baseline note)
cd app     && npm run test          # 51 passed
cd app     && npm run build         # succeeds
```

**Baseline note.** Five tests in `test_ble_scanner.py` fail whenever a Five12
backend is running on the same machine: it holds the OS-level adapter lock those
tests need. That is environmental, not a regression. Stop the backend for a
clean run.

## Release blockers — the read-only ones, narrowed

"No write path anywhere" became **"no write path outside the four-command
allowlist."** The four guard tests were inverted in the same commits that broke
them, never in a separate cleanup, so no revision of this branch exists in which
writes are possible and the guards are absent.

- The client names a command; the server maps it to a UUID and a payload byte.
  A client cannot name either. `WRITABLE_UUIDS` is derived from the table, so a
  new command cannot silently widen the allowlist.
- Every check is server-side and runs before any byte moves: allowlist,
  single-use server-issued confirmation, device identity, snapshot freshness,
  mode gate.
- Still nothing named `linked`. An ATT acknowledgement is `attAcknowledged`.
- "Accepted, unverified" is a first-class operator-visible outcome for mode
  writes — never smoothed into success, never raised as an error.

## Deferred minors — triaged by the final whole-branch review, ship as-is

| Item | Why it is fine |
|---|---|
| `required_mode: tuple` not `tuple[str, ...]` | Annotation polish on a frozen table |
| `link`/`unlink` payloads are bare `0x05`/`0x00`, no `LinkAction` enum | Tests pin the exact bytes, so drift cannot go unnoticed |
| No machine check that warning copy stays prospective | Two substring denylists were tried and both false-positived on legitimate English; the invariant is enforced structurally on the result payload instead |
| Nothing asserts `connect_for_write` yields the write adapter | Single expression, no branch |
| `command_service.py` holds command policy *and* token lifecycle | 455 lines; splitting now adds churn to the file most worth keeping stable |
| TOCTOU between the registry pre-check and coroutine execution yields 409 not 404 | Both are typed refusals; neither writes |
| `_catch_sim_errors` handlers are no-ops on the real path | Renamed and documented |
| No focus trap on the confirmation dialog | Changing selection fires the reset effect, which closes the dialog |
| `CintennaPanel.jsx` at ~410 lines, 10 state values | Extract a write-control hook when the next control lands |

**One deliberately left open:** the audit `except BleError` guard closes before
the verification phase, so an exception inside `_verify_after_reboot` leaves a
landed write with no audit line. Narrow, and the write itself is already
recorded on the success path.

## What the hardware run must settle

Two numbers in the code are provisional and were deliberately not guessed:

- `REBOOT_REDISCOVERY_TIMEOUT_S = 30.0` — measure the real reboot-and-
  re-advertise time and raise the constant if it is exceeded.
- Whether device identity survives a mode-change reboot. If it does not, the
  panel must ask the operator to re-select the radio rather than acting on a
  stale selection.

**Link is the hazardous step.** It puts a transmitter into pairing mode and any
unpaired receiver in range attaches to it — not only the intended one. That run
needs RF isolation or knowingly accepted risk. Not during a show.
