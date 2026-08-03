# Astera ART7 — Stage A (read-only, gated, simulator-first)

- **Agent:** Claude Code
- **Branch:** `feat/claude/astera-stage-a` (base `origin/main` @ `e3c4bb7`)
- **Status:** implemented, review requested from Hermes —
  `docs/coordination/reviews/2026-08-03--claude-astera-stage-a-handoff.md`
- **Date:** 2026-08-03

## Authority

Implements exactly the Stage A direction locked in:

- `docs/agent-reviews/2026-07-29-claude-review-of-astera-integration-spec.md`
  (B1–B6, all accepted)
- KB `Hermes/Reviews/2026-07-29-hermes-response-to-claude-five12-art7-review.md`
  (@ `73f3a39` on `plan/five12-art7-device-integration`)

Anthony asked for this to start 2026-08-03, **with live Asteras on set** — see
Live-set discipline below.

## What landed

| Piece | Where |
|---|---|
| `AsteraAdapter(DeviceAdapter)`, synchronous, read-only | `backend/app/integrations/astera.py` |
| Registry + device listing | `backend/app/integrations/__init__.py` (`ALL_DEVICE_IDS` + `get_adapter`) |
| Gate constant, default OFF, both runtimes | `backend/config.py` (`ENABLE_ASTERA_TOOLS`) |
| Devices-tab panel | `app/src/components/devices/AsteraPanel.jsx`, registered in `Devices.jsx` |
| Backend tests (31) | `backend/tests/test_astera_{gate,detect_and_sim,fetch,normalize,registry}.py` |
| Frontend tests (6) | `app/src/components/devices/AsteraPanel.test.jsx` |

No new routes (generic `/api/devices/*` three), no new dependency, no backend
polling loop, no integration CRUD, no request-supplied target — per B1–B3.

## The gate contract (the load-bearing piece)

`FIVE12_ASTERA_TOOLS` unset/`0` (default): the adapter performs **no network
activity of any kind** — no DNS resolution, no TCP probe, no HTTP. Enforced in
tests by poisoning `socket.getaddrinfo`, `socket.create_connection`, and
`requests.get`; a single call fails the suite. The disabled card reads
"disabled", never "searched and absent". The gate governs sim mode too.
Gate on + no `FIVE12_ASTERA_HOST`: names the exact setting, still no request.

## HTTP boundary (B4/B5)

`require_private_host()` reused (resolved-IP-in-URL, no second lookup), plus:
redirects refused (`allow_redirects=False` **and** 3xx rejected), response
streamed and capped at 1 MiB, `application/json` content type required, IPv6
literals bracketed, IPv6 link-local refused until zone handling is designed.
The fetch takes a **key into `ENDPOINTS`** (`status`, `targets`), never a
path — AsteraNext's state-changing GET routes (`/api/launch`,
`/api/set_power`, …) are unreachable by construction and never referenced.

## Honesty labels

- `VERIFIED_AGAINST_UNIT = False`; every real read carries
  `protocolVerified: false` — payload shapes are static-analysis hypotheses
  from AsteraNext 13.18, no live server has been captured. The normalizer
  reads missing fields as `null`, never guesses.
- Simulated data carries `simulated: true` and a loud badge; the sim models
  only the normalized Five12 contract.
- The raw Radio PIN never appears in status, history, or the UI — only a
  deterministic `PIN-XXXX` alias (hygiene, not secrecy; documented in code).

## Live-set discipline (2026-08-03 session)

Implemented and tested with working Asteras on set. Zero packets were sent to
any fixture, phone, or ART7: all tests run against poisoned sockets, fakes, or
the simulator, and the gate defaults off. **Do not set `FIVE12_ASTERA_TOOLS=1`
against the show network until the bench session has verified the protocol on
an isolated ART7 + dummy fixtures.**

## Verification

- Backend: **581 passed, 7 skipped, 0 failed** — full suite, app interpreter
  (`Python312\python.exe -m pytest` from `backend/`), Astera tests included.
  Every Astera test was watched red before its implementation existed.
- Frontend: **80 passed** (`npx vitest run`), `npm run build` clean.

## Not done, deliberately

- Bench capture against a real AsteraNext server (protocol stays unverified;
  field mapping in `_normalize` is the thing the capture will correct).
- Last-known-good caching / failure backoff (allowed as "may" — omitted until
  a real polling session shows it's needed).
- Stage B (direct ART7 transport) — **blocked** until BLE GATT vs Classic
  RFCOMM is established in a safe, isolated discovery session.
