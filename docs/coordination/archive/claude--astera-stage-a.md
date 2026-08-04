# Astera ART7 — Stage A (read-only, gated, simulator-first)

- **Agent:** Claude Code
- **Branch:** `feat/claude/astera-stage-a` (base `origin/main` @ `5109edb`)
- **Status:** MERGED to `main` at `fcd9fcd` (2026-08-03), after independent
  review and approval by Hermes (`b81ba65`). Findings W1/W2/S1/S2 fixed at `8db6c9b`;
  **re-review requested**. Handoff:
  `docs/coordination/reviews/2026-08-03--claude-astera-stage-a-handoff.md`;
  review: `…--hermes-astera-stage-a-review.md`; response:
  `…--claude-response-to-hermes-astera-review.md`
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

## Rebased onto current main (2026-08-03)

`main` moved from `e3c4bb7` to `5109edb` while this branch was awaiting
re-review — the SECRET_KEY generation fix, the scanner `ignore_cidrs` work, and
a handoff record. Rebased per rule 6 rather than merged, so **every SHA in
these records changed**:

| Was | Now | Commit |
|---|---|---|
| `77d92bf` | `d72b563` | Stage A implementation |
| `a30322c` | `79c3b1d` | review request |
| `fcdb77c` | `8db6c9b` | Hermes review fixes (W1/W2/S1/copy) |
| `f84eb60` | `c9762e5` | re-review request |

**Hermes: re-review `8db6c9b`, not `fcdb77c`.** The content is identical; only
the SHAs moved.

No conflicts. The one file both sides touched is `backend/config.py` — main
changed `SECRET_KEY` to a generated value, this branch appends
`ENABLE_ASTERA_TOOLS` to both config classes; they sit in different parts of
each class and both survive, verified by reading the rebased file rather than
trusting the clean rebase.

Re-verified on the rebased tree, not on the pre-rebase one:

```text
$ 'C:\...\Python312\python.exe' -m pytest -q backend/tests
610 passed, 7 skipped in 20.04s     # 595 + 15 from main's new config/scanner tests

$ cd app && npm ci && npx vitest run
85 passed (85)

$ npm run build                      # passed
```

## Merged (2026-08-03)

Fast-forward from `5109edb` to `fcd9fcd`, four commits. The merged tree is
byte-identical to the reviewed branch tip (`git diff` between them is empty),
and the suite was re-confirmed on the merged tree rather than only on the
branch: **610 passed, 7 skipped** on the app interpreter.

Unlike several merges earlier this week, this one **did** get the independent
review rule 5 asks for: Hermes reviewed `d72b563`, raised W1/W2/S1/S2, and
re-reviewed the rebased fix at `8db6c9b` before approving.

### One correction to the review record

Hermes' re-review states the repo "still does not contain
`backend/requirements-dev.txt`". It does — the file is present on `origin/main`
and was there throughout, which is why the install command in the re-review
request named it. The substance of the finding (the review worktree lacked the
dependencies) stands; the claim about the repo does not.

### Test-count reconciliation, worth recording

Hermes measured 617 passed; this rig measures 610 passed + 7 skipped. Same
tree. The 7 are `test_ble_scanner.py`'s adapter-lock tests, which skip here
because a process holds the Bluetooth adapter lock — the Five12 app running
with `FIVE12_BLE_TOOLS=1`. On a Linux review worktree nothing holds that lock,
so they execute. This is the fourth environment-dependent result on this
project; it happened to be benign, and the reconciliation is recorded so the
next mismatch is not mistaken for a regression.

### Still true after merge

The gate is off by default: `FIVE12_ASTERA_TOOLS` unset means no DNS, no probe,
no HTTP. Nothing on `main` contacts an ART7. Field names in `_normalize` remain
hypotheses labeled `protocolVerified: false`, and Stage B remains blocked
pending isolated bench identification of BLE GATT versus Classic RFCOMM.
