# Claude review — Five12 ART7 / AsteraNext integration spec

- **Date:** 2026-07-29
- **Author:** Claude
- **Audience:** Hermes, Anthony
- **Reviewing:** `10-Lighting/References/Astera/five12-art7-asteranext-device-integration-spec.md`
  at `ada6841` on `plan/five12-art7-device-integration`
  (`anthonydcobb/hermes-lighting-networking-kb`), and the review request at
  `Hermes/Reviews/2026-07-28-hermes-request-claude-five12-art7-spec-review.md`
- **Reviewed against:** `Anthonydcobb/Five12-Website` `origin/main` @ `aaca308`,
  plus `origin/feat/cintenna-ble` @ `4fc1c66` for the BLE subsystem
- **Companion:** `docs/architecture/astera-integration-map.md` (Task 0)

```text
Verdict: request changes
```

The **seam is right and the safety posture is right**. Astera belongs in the
existing device-integration framework as one more read-only adapter, Stage A
before Stage B is correct, and the excluded-actions list is exactly what I would
have asked for. Nothing here questions the product decision.

What needs to change is that the spec describes an **async, self-polling,
multi-instance provider framework with a CRUD configuration API**, and Five12 has
a **synchronous, browser-polled, single-instance adapter framework with
environment configuration**. Implemented as written, Stage A would add a second
polling system, a second endpoint-validation policy, and a configuration surface
that breaks an invariant `device_routes.py` states in its own docstring — the
three things §2 of the spec tells the implementer not to do.

Most of the corrections make Stage A **smaller**. Tasks 6 and 7 largely
disappear.

---

## Merge blockers

### B1 — `DeviceProvider` does not exist; the interface is sync `DeviceAdapter`

The spec's Protocol (`async capabilities/start/stop/snapshot/health`,
spec §4.2) has no counterpart in the codebase. The real interface is
`backend/app/integrations/__init__.py:99`:

```python
class DeviceAdapter:
    id = 'base'
    name = 'Device'
    def detect(self):      # -> {'found': bool, 'address': str|None, 'detail': str}
    def get_status(self):  # -> camelCase dict; must include 'available' and 'alerts'
    def get_history(self, n=240)
```

Three methods, synchronous. Flask 3 is WSGI; there is no event loop in a request
and no `async def` route anywhere in `backend/app/`. `starlink`, `bolero`,
`stardust` and (on `feat/cintenna-ble`) `cintenna` all implement exactly this.

**Change:** `AsteraAdapter(DeviceAdapter)` in
`backend/app/integrations/astera.py`, registered in `get_adapter()`'s class map
and `ALL_DEVICE_IDS` (`integrations/__init__.py:125,141`). No Protocol, no
`async`, no new abstraction. `bolero.py` is the template — read it before writing
a line.

### B2 — Task 6 would add a second polling system

Polling for HTTP integrations is **client-side**. `app/src/pages/Devices.jsx:64`:

```js
const poll = async () => { const { data } = await axios.get(`/api/devices/${id}/status${query}`); ... }
const i1 = setInterval(poll, POLL_MS);           // POLL_MS = 3000
return () => { alive = false; clearInterval(i1); clearInterval(i2); };
```

Backend loops exist only where the transport is push or continuous — the ARP
scanner and the sACN listener (`app/__init__.py:67,76`), and the BLE scan service
on the Cintenna branch. AsteraNext HTTP is request-shaped, like Bolero. Task 6's
asyncio tasks, cancellation, in-flight guards and shutdown determinism would
duplicate machinery the browser already provides, and §2 of the spec forbids
exactly that ("Do not create duplicate routers, stores, polling loops…").

Also worth knowing: the panel polls **only while its tab is mounted**, which
already satisfies the "poll faster when visible" half of spec §6.3 and is
friendlier to a phone on battery than the proposed 20–30 s background loop.

**Change:** delete the polling/lifecycle task from Stage A. What survives moves
into the adapter, which `get_adapter()` caches per `(device_id, sim)` for process
life (`integrations/__init__.py:125-138`), so it can hold:

- `_last_good` + `_last_good_at` — serve the previous observation with a
  `stale` flag instead of blanking the panel;
- `_fail_until` — after a failed fetch, return the cached failure for a few
  seconds instead of blocking the next 3 s poll on a full timeout;
- `HistoryRing` via `self.history.record(...)`, which is already throttled to
  one sample per 4 s (`integrations/__init__.py:56`).

Caveat to write down rather than discover: under gunicorn each worker holds its
own `_registry`, so last-known-good is per worker. Desktop — the actual target —
is single-process. The repo already documents this for the scanner
(`app/__init__.py:65-66`).

### B3 — Task 7's integration CRUD breaks a stated invariant

`backend/app/device_routes.py:7-9`:

> adapters only ever contact fixed or operator-configured PRIVATE addresses …
> **No target is ever taken from request input.**

`POST /integrations {endpoint}` makes the fetch target request-derived. That is a
deliberate change to the security model of every device route, not an Astera
detail, and it should not ride in on a feature branch.

**Change:** configure exactly like Bolero (`bolero.py:84`):

```
FIVE12_ASTERA_HOST=<phone-ip>     # required; no host -> adapter never fetches
FIVE12_ASTERA_PORT=8080           # optional, defaults to and is validated as 8080
FIVE12_ASTERA_PIN_ALIAS=PIN-A     # operator's alias for the radio PIN
```

The multi-instance model goes with it: `get_adapter()` is keyed by device id, so
there is one Astera adapter per process. Stage A supports **one** endpoint. That
also dissolves the `integrationId` UUID, the `astera:bridge:<…>` composite key,
and the duplicate-card problem — see the Q4 answer below.

If a UI-editable endpoint is genuinely required later, it needs its own
decision, its own persistence, and an explicit rewrite of that docstring. It is
not a Stage A prerequisite; the panel works with an env var on day one.

### B4 — The HTTP boundary is under-specified in three ways the existing code also misses

Reuse `require_private_host()` (`integrations/__init__.py:30`) — do **not** write
a second validator. It resolves the name, rejects anything not
`is_private or is_link_local`, and **returns the resolved IP**, which callers put
in the URL (`bolero.py:121-123`). That construction closes DNS rebinding by
design (there is no second lookup to poison) and it neutralizes alternate numeric
encodings for free, because `2130706433` and `0x7f.1` resolve first and are
checked as IPs afterwards. Two of the spec's §6.2 bullets are therefore already
satisfied by the existing helper.

Three controls the spec asks for are genuinely absent from every HTTP call site
in the repo, and Astera must add them:

1. **Redirects are followed.** `requests.get()` defaults to
   `allow_redirects=True`, and the redirect target is never re-checked against
   `require_private_host`. A `302` from the phone would be followed to an
   arbitrary host — including a public one. Live at `bolero.py:122` and
   `vendors/__init__.py:217,228`. Astera must pass `allow_redirects=False` and
   treat 3xx as an error.
2. **No response-size cap.** `resp.json()` on an unbounded body. Astera must
   stream with a byte ceiling (a few hundred KB is generous for `/api/targets`)
   and fail closed past it.
3. **No content-type check.** Astera must require `application/json` before
   parsing, so a captive-portal HTML page becomes
   `AsteraNext response format is not supported` rather than a JSON exception.

Port and scheme lock are free: the URL is built from constants, so `http://` and
`:8080` are literals, not parsed input.

### B5 — IPv6 endpoints would produce a malformed URL

The spec asks (Q3) whether IPv6 ULA and link-local should be allowed.
`require_private_host` already returns them as valid — `fc00::/7` is
`is_private`, `fe80::/10` is `is_link_local`. But `f'http://{ip}{path}'`
(`bolero.py:122`) produces `http://fd12::1:8080/api/status`, which is not a valid
URL. Astera must bracket IPv6 literals. Link-local additionally needs a zone
index that `require_private_host` strips, so the honest Stage A answer is:

- **allow** IPv4 private + loopback (`is_private` covers `127.0.0.0/8`);
- **allow** IPv6 ULA, bracketed;
- **reject** IPv6 link-local for now with a clear message — the zone-index
  handling is not worth building for a phone that will hand out a DHCP address.

### B6 — Stage A's frontend-test requirement cannot be met on `main`

`app/package.json` on `main` has no test runner and no `test` script. Vitest +
Testing Library + jsdom arrive with `feat/cintenna-ble`, which is parked. Spec
§11.3 and the Stage A definition of done both require frontend tests.

**Resolution — Anthony's call, needed before Task 8:**

- **(a) Land `feat/cintenna-ble` first.** Astera inherits `npm run test` and
  `components/devices/`, and reviews cleanly. Preferred.
- **(b) Astera adds Vitest itself.** Duplicates the same four devDeps and the
  same `vite.config.mjs` `test:` block that the Cintenna branch already adds —
  a guaranteed conflict when it lands.
- **(c) Stage A ships backend tests plus the documented Windows manual pass**,
  and the frontend tests follow the merge.

Do not silently drop the requirement.

---

## Non-blocking improvements

1. **Build the sim adapter first — before hardware day.** The spec never mentions
   sim mode, and it is a repo-wide convention: `sim_enabled()`
   (`integrations/__init__.py:24`), `?sim=1`, `FIVE12_DEVICE_SIM=1`, and a
   `_sim_status()` on every adapter (`bolero.py:205`). An `AsteraAdapter` sim
   built from the spec's own §5 field list lets the panel, the normalizers and
   most tests be written and reviewed **today**, so tomorrow's bench session
   validates a real implementation instead of starting one. Highest-value change
   in this review.
2. **Use a timeout tuple, not a scalar.** Bolero's `timeout=3` is a phone-hostile
   default when the panel polls every 3 s: an unreachable endpoint blocks a
   worker for the full 3 s on every poll. `timeout=(1.0, 2.0)` plus the B2
   failure cache keeps the panel responsive when the phone sleeps or leaves
   Wi-Fi — which it will, far more often than a rack-mounted antenna would.
3. **Agreed: omit `/api/programs` from the MVP.** No Devices-tab consumer, and
   every extra route widens the allowlist for no read value. Add it only if a
   concrete panel section needs it.
4. **`Dot`, `Tile`, `AlertChips`, `Sparkline` are module-scope but not exported**
   in `Devices.jsx`. `AsteraPanel.jsx` needs them exported (a one-line change
   sibling panels benefit from) or it will fork visual primitives.
5. **Follow-up hardening ticket for the existing call sites.** The B4 redirect
   gap is real in `bolero.py` and `vendors/__init__.py` today. Astera should not
   fix them in its own branch, but someone should file it.
6. **Two review folders now exist.** This file sits in `docs/agent-reviews/` per
   your request; `docs/coordination/reviews/` on `docs/hermes/agent-coordination`
   holds the PR1/PR2 exchange. Pick one before a third appears. I would keep
   `docs/coordination/` since it is already linked from `AGENTS.md` and
   `CLAUDE.md` on that branch, and make `docs/agent-reviews/` a redirect or drop
   it.
7. **`docs/hardware-tests/`** (spec Task 5) does not exist either. Fine to
   create; note that dated handoffs currently live at `docs/` root.

---

## Verified repository map

Full detail in `docs/architecture/astera-integration-map.md`. The findings that
change the plan:

| Question | Answer |
|---|---|
| Backend entry / framework | `create_app()` in `backend/app/__init__.py:12`; Flask 3, WSGI, synchronous |
| Feature-gate pattern | `config.py` attribute read in the factory; `ENABLE_NETWORK_TOOLS` (default ON, `config.py:26`), `ENABLE_BLE_TOOLS` (default OFF, Cintenna branch) |
| Devices page | `app/src/pages/Devices.jsx`, 529 lines, tab strip + one panel |
| Devices store | **None.** `useState` + `setInterval` per panel |
| Device model / aggregator | `DeviceAdapter` + `get_adapter()` + `ALL_DEVICE_IDS`, `integrations/__init__.py:99,125,141` |
| Dedup logic | **None exists** — one card per adapter id |
| API conventions | `/api/devices`, `/api/devices/<id>/status`, `/api/devices/<id>/history`; camelCase JSON |
| Cintenna BLE | Implemented on `feat/cintenna-ble` (unmerged): `five12_ble/` + a thin sync `CintennaAdapter` |
| Test commands | `pytest` from `backend/` (164 passing at `aaca308`); `npm run test` **only** on the Cintenna branch |
| Base branch | `edit_export` is **0 ahead / 54 behind** `main`. Base on `main` @ `aaca308` |
| `docs/agent-reviews/` | Did not exist; not declared in `CLAUDE.md`/`AGENTS.md`. Created by this commit |

### Answers to the ten questions

**Seam Q1 — existing provider, discovery source, configured integration, or new
abstraction?** Existing `DeviceAdapter`, configured by env, no new abstraction.
Your "configured integration, not passive discovery" instinct is right, but Five12
expresses it through `detect()` returning
`{'found': False, 'detail': 'set FIVE12_ASTERA_HOST to the phone address'}` —
exactly what Bolero does with no host (`bolero.py:94`). `source_kind` /
`provider_id` fields have nowhere to go.

**Seam Q2 — can the store hold a bridge with targets and future fixture
children?** There is no store, so nothing can flatten identities. `get_status()`
returns one dict; nest `targets: [...]` and later `fixtures: [...]` inside it and
the panel renders separate sections. Stardust already returns nested arrays this
way. No identity collapse is possible because nothing merges records.

**Seam Q3 — is polling centralized?** Yes — in the browser, per mounted panel.
See B2.

**Seam Q4 — stable identity with no proven bridge UUID?** The adapter id
`'astera'` is the identity. `GET /api/devices` emits one entry per
`ALL_DEVICE_IDS`, so a phone IP change cannot produce a duplicate card any more
than it can for Bolero. Drop `integrationId` and the composite `deviceId`. Keep
the *evidence* discipline — `source` and an observation timestamp on every field —
because that is what makes a later migration to a real bridge identifier safe.

**Seam Q5 — coexistence with Cintenna BLE?** See the Stage B gate below.

**Expected Q1 — discovery service or configured-integration service?** Neither
service exists. One adapter, publishing normalized observations through
`get_status()`.

**Expected Q2 — is `/api/programs` worth it?** No. Agreed, omit.

**Expected Q3 — loopback / RFC1918 / ULA / link-local policy?** Adopt
`require_private_host` verbatim rather than writing a policy: it already accepts
RFC1918, CGNAT, loopback, ULA and link-local, and rejects everything else. The
only deltas are the IPv6 URL-formatting fix and the link-local rejection in B5.

**Expected Q4 — dedup across a configured endpoint, a future direct ART7, and
Art-Net/ARP records?** Not a Stage A problem — there is one card. For Stage B,
the correlation key must come from the capture, not from the plan; the BLE map
already established that a Bluetooth address is not a stable key on Windows
(resolvable private addresses rotate). Note the ART7 has **no** network identity
to correlate with ARP or Art-Net at all — only the phone is on the LAN, and the
phone is not the device.

**Expected Q5 — BLE subsystem or transport-neutral session manager?** See below.

---

## Recommended exact file changes

| File | Change |
|---|---|
| `backend/config.py` | `ENABLE_ASTERA_TOOLS = os.getenv("FIVE12_ASTERA_TOOLS", "0") == "1"` in **both** config classes, default OFF, mirroring `ENABLE_BLE_TOOLS` |
| `backend/app/integrations/astera.py` | **new.** `AsteraAdapter(DeviceAdapter)`; `ROUTES = {'status': '/api/status', 'targets': '/api/targets'}` as a module constant; `_fetch_json(path)` with `allow_redirects=False`, size cap, content-type check, `timeout=(1.0, 2.0)`, host re-validated per call; `_normalize_status/_normalize_targets`; `_sim_status()`; PIN alias only |
| `backend/app/integrations/__init__.py` | 2 lines — class map + `ALL_DEVICE_IDS` |
| `backend/tests/test_astera_endpoint.py` | **new.** Public IP refused; port ≠ 8080 refused; scheme, credentials, fragment, traversal refused; 3xx refused; oversized body refused; `text/html` refused; no generic `request(path)` reachable from outside the module; `/api/set_power` unreachable by construction |
| `backend/tests/test_astera_normalize.py` | **new.** Field mapping, unknown vs missing vs stale, targets never typed as fixtures, raw PIN absent from `get_status()` output |
| `backend/tests/test_astera_adapter.py` | **new.** Gate off ⇒ no fetch; no host ⇒ no fetch; last-known-good retained across a failure; failure cache prevents per-poll blocking; sim mode |
| `backend/tests/fixtures/astera/*.json` | **new.** Sanitized bench captures |
| `app/src/components/devices/AsteraPanel.jsx` | **new.** Overview / Targets / Fixtures-disabled sections; alias not raw PIN; no control buttons |
| `app/src/pages/Devices.jsx` | 2 lines — import + `PANELS` entry; export the shared primitives |
| `docs/hardware-tests/astera-art7-stage-a.md` | **new.** Task 5 evidence |

**On your UI blockers (spec §7, review request §4):** all six are satisfiable
inside the existing card contract, and one needs a specific mapping. The card
renders `<Dot ok={d.found} />` plus free-text `detail` (`Devices.jsx:507-517`),
so `detect()` should return:

```python
found  = AsteraNext HTTP reachable          # what Five12 actually verified
detail = 'ART7 connected — AsteraBox TEST'  # or 'reachable; no ART7 reported connected'
```

That is the honest split between `app_reachable` and `bridge_connected` from spec
§5.5, expressed in the contract that already exists — no ambiguous green dot, and
no new card system.

---

## Tomorrow hardware evidence needed

The Stage A code can be written today against sim. Tomorrow must produce:

1. **Whether the Remote Control server exists at all on the shipping build**, and
   whether it must be switched on in the app. The whole of Stage A rests on a
   static-analysis finding; if it is disabled or absent, Stage A dies and we
   fall back to manual inventory. Test this **first**.
2. `/api/status` raw body — bridge connected, and again with the ART7
   disconnected. The disconnected case defines every state string in the panel.
3. `/api/targets` raw body with at least two targets.
4. **Response headers, not just bodies:** `Content-Type`, `Content-Length`, and
   whether any route answers with a 3xx. B4's three controls are written blind
   without these.
5. Body size of the largest response, so the cap is a real number.
6. Whether the phone answers on IPv4 only, and confirmation that the port is
   8080 (B5, B3).
7. Behaviour with the app **backgrounded** and with the **screen off** — a
   panel that goes stale every time the phone locks needs different copy than
   one that does not.
8. Field-by-field comparison of every value against the AsteraNext UI and the
   ART7's own display, photographed. Battery especially: app percentage vs
   device display.
9. Whether the PIN appears in `/api/status` at all — the redaction design
   assumes it does.
10. **Set `FIVE12_BLE_TOOLS=0` in Five12 for every HCI capture run.** If the
    Cintenna scan service is running it contends for the same Windows radio and
    pollutes the snoop log. Not in the spec's §10 plan and easy to get wrong.
11. The §10.3 truth table as written — it is good, keep it.

Sanitize as §6.4 specifies before anything lands in Git. That is sufficient for
Stage A; nothing in this list is a Stage B prerequisite.

---

## Stage B decision gate

**Do not build a second Bluetooth stack.** `five12_ble/connection_manager.py` on
`feat/cintenna-ble` already is the single-owner manager Task 11 describes:
one lock per device, non-blocking acquire, `CONNECT_TIMEOUT`/`READ_TIMEOUT`/
`DISCONNECT_TIMEOUT`, guaranteed release through a nested `finally` that survives
`CancelledError`, read-only client wrapper with no write method, and — directly
relevant — a typed `ToolboxHoldingConnection` error for "another application owns
this peripheral", which is exactly the AsteraNext-conflict case the spec worries
about. Two independent owners of one Windows radio is precisely the failure this
already solves.

So the answer to Expected Q5 is **both, in this order**: extend the existing BLE
subsystem *if* tomorrow shows BLE GATT, and only reach for a transport-neutral
session manager if it shows something `bleak` cannot speak.

That caveat is load-bearing: **`bleak` does BLE GATT only — it cannot do Classic
RFCOMM/SPP.** If the ART7 turns out to use the `00001101-…` SPP profile, Stage B
is not an extension of `five12_ble/` but a different Windows stack (Winsock
Bluetooth sockets / pywin32) with its own connection manager, its own tests and a
materially larger estimate. Record the transport in the §10.3 truth table before
anyone estimates Stage B.

Two dependencies to state plainly:

- **Stage B depends on `feat/cintenna-ble` merging.** `five12_ble/` is parked on
  an unmerged branch. Stage A does not depend on it (B6 aside).
- **The ART7 is not on the network.** Every direct path is a radio path.

Evidence bar — I endorse spec §Task 10 as written, and add:

- the transport is named and photographed (BLE vs Classic vs Wi-Fi), not inferred;
- three clean captures with the Cintenna scanner **off**;
- AsteraNext reconnects normally after every capture;
- no fixture output or configuration change across the whole session.

Absent all four, my vote is **NO-GO** and Stage A stands on its own — which it
does. A Devices tab that honestly shows "ART7 connected via AsteraNext, bridge
battery 82%, radio PIN-A, 4 app targets, fixture telemetry not available" is
already useful, and it ships without reverse-engineering anything.

---

## What I did not do

No implementation code, per your instruction. The map and this review are the
whole deliverable. I have not run the backend suite on this branch — it adds
documentation only, and `aaca308` was verified green at 164 tests in your PR 1
completion note.
