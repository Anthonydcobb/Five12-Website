# Handoff — Astera ART7 Stage A (read-only, gated, simulator-first)

- **Owner:** Claude Code
- **Reviewer:** Hermes Agent — **review requested**
- **Branch:** `feat/claude/astera-stage-a`
- **Base / head SHA:** base `e3c4bb7` (`origin/main`) / head `77d92bf`
- **Status:** review
- **Hardware evidence:** `simulated` — no ART7, phone, or fixture was contacted

## Role note

Your 2026-07-29 response (KB
`Hermes/Reviews/2026-07-29-hermes-response-to-claude-five12-art7-review.md`,
`73f3a39`) ended with you implementing and Claude reviewing. Nothing had landed
by 2026-08-03; Anthony asked Claude Code to start, so the seats are swapped for
this branch — Claude implemented, and the independent review under rule 5 is
yours. The implementation follows the direction you locked in, not a new one.

## What changed

One synchronous `AsteraAdapter` on the existing `DeviceAdapter` seam, per
B1–B6 as you accepted them. No async provider framework, no backend polling
loop, no integration CRUD, no request-supplied target, no new route, no new
dependency. Astera appears through the generic `/api/devices/*` three.

Gate contract, implemented as behavior rather than a config constant:

- `FIVE12_ASTERA_TOOLS` unset or `0` (the default): **no network activity of
  any kind** — no DNS resolution, no TCP probe, no HTTP. Enforced by tests
  that poison `socket.getaddrinfo`, `socket.create_connection` and
  `requests.get`; one call fails the suite.
- Disabled copy says "disabled", never implies the ART7 was searched for and
  found absent — asserted in both backend and frontend tests.
- The gate governs **sim mode too**, which is stricter than `FIVE12_DEVICE_SIM`
  elsewhere in the app. Flagged below as a decision to check.
- Gate on with no `FIVE12_ASTERA_HOST`: names the exact setting, still no
  request.

HTTP boundary (B4/B5): `require_private_host()` reused unchanged
(resolved-IP-in-URL, so no second lookup to rebind), plus redirect refusal
(`allow_redirects=False` **and** an explicit 3xx rejection), a streamed 1 MiB
response cap, an `application/json` content-type requirement, IPv6 literal
bracketing, and IPv6 link-local refusal until zone handling is designed.

`_fetch_json` takes a **key into `ENDPOINTS`**, never a path. The allowlist is
`status` → `/api/status` and `targets` → `/api/targets`. AsteraNext's
state-changing GET routes (`/api/launch`, `/api/select_target`,
`/api/set_brightness`, `/api/set_power`, the developer action route) are
unreachable by construction and are named nowhere except the module docstring
that explains why they must not be added. `/api/programs` is out of the MVP as
agreed.

Honesty labels: `VERIFIED_AGAINST_UNIT = False`, and every real read carries
`protocolVerified: false`. The raw Radio PIN never reaches status, history, or
the UI — only a deterministic `PIN-XXXX` alias. Simulated data carries
`simulated: true` plus a visible badge and models only the normalized Five12
contract.

## Why this approach

The whole design follows your accepted corrections; the only places I chose
rather than followed are the three listed under "most worth your scrutiny".

The gate reads the environment variable at **call time**, not construction,
because `get_adapter()` caches one adapter instance per `(device, sim)` for
process life — a constructor read would let a cached instance outlive an
operator flipping the gate. `config.py` still carries `ENABLE_ASTERA_TOOLS` in
both config classes as the documented switch, and a test pins both to `False`
by default.

The normalizer reads every field defensively and returns `None` for anything
missing, rather than defaulting. A guessed value that renders as a real one is
the failure mode this project has now hit twice (the Bolero antenna
attribution, the `[VERIFIED]` docstring that was wrong); with a protocol this
unverified, a blank is the honest output.

## Files and contracts affected

| File | Change |
|---|---|
| `backend/app/integrations/astera.py` | new — adapter, gate, hardened fetch, normalizer, simulator |
| `backend/app/integrations/__init__.py` | `ALL_DEVICE_IDS` + `get_adapter` registration (shared central file — see risks) |
| `backend/config.py` | `ENABLE_ASTERA_TOOLS`, both config classes, default off |
| `app/src/components/devices/AsteraPanel.jsx` | new panel |
| `app/src/pages/Devices.jsx` | `PANELS` registration + import |
| `backend/tests/test_astera_{gate,detect_and_sim,fetch,normalize,registry}.py` | new, 31 tests |
| `app/src/components/devices/AsteraPanel.test.jsx` | new, 6 tests |
| `docs/coordination/active/claude--astera-stage-a.md` | active record |

**Contract changes:** `ALL_DEVICE_IDS` gains `'astera'`, so `GET /api/devices`
returns a fifth row. No response shape changed. No new route, no schema change,
**no migration**, no new dependency (`requests==2.32.3` was already pinned).

## Verification actually run

Canonical checks, in the documented form, on the interpreter `start.ps1`
launches the app with:

```text
$ 'C:\...\Python312\python.exe' -m pytest -q backend/tests
581 passed, 7 skipped, 126 warnings in 16.99s

$ cd app && npm ci && npx vitest run
80 passed (80)

$ npm run build
✓ built in 3.71s

$ git status --short          # clean
$ git diff --check            # clean
```

Every one of the 37 Astera tests was watched failing, for the expected reason,
before the code that satisfies it existed.

The 7 skips are the pre-existing BLE adapter-lock tests standing down, not
anything from this branch.

## Operator acceptance test

**Not yet runnable, deliberately.** The acceptance test is your Phase 1/2 bench
session: one isolated ART7, dummy fixtures, an isolated test Wi-Fi network,
AsteraNext RemoteControl enabled, then `FIVE12_ASTERA_TOOLS=1` and
`FIVE12_ASTERA_HOST=<phone-ip>` and a manual read of `/api/status` and
`/api/targets` compared field-by-field against the app screen.

Until then the only supported acceptance path is `?sim=1`, which is labeled
simulated end to end.

## Known risks / skipped checks

- **The normalizer's field names are unverified.** This is the main risk and it
  is disclosed in code, in the payload, and here.
- **Live Asteras were on set while this was written** (2026-08-03). Zero packets
  were sent to any fixture, phone, or ART7 — poisoned sockets, fakes, simulator,
  gate off by default. The gate must stay off against the show network until
  the bench session.
- **Rule 4, shared central file:** this branch edits
  `backend/app/integrations/__init__.py` (two lines: registry entry and
  `ALL_DEVICE_IDS`). No other active note reserves it as of `e3c4bb7`, but it
  is a collision-prone path and worth re-checking before integration.
- **Not implemented, allowed but not required:** last-known-good caching and
  bounded failure backoff. Your response permitted them ("may"); omitted until
  a real polling session shows they are needed.
- **Stage B remains blocked** — no transport work, no estimate, pending
  BLE GATT vs Classic RFCOMM identification in a safe discovery session.
- **Pre-existing, not from this branch:** three `.pyc` files are tracked on
  `origin/main` (`git ls-files | grep '\.pyc$'` returns 3 on `e3c4bb7`). The
  hygiene check in the README is therefore not clean on main. Left alone —
  outside this branch's scope, flagged for whoever owns cleanup.

## Most worth your scrutiny

1. **The hypothesized field names.** `_normalize` maps `online`, `pin`,
   `version`, `platform`, `bridge.name`, `bridge.battery`, and
   `targets[].{id,name,selected,brightness}`. These are plausible spellings
   chosen from your static analysis of AsteraNext 13.18 — they are exactly the
   part with no ground truth, and the bench capture is what corrects them. If
   you have stronger evidence for any spelling from the disassembly, that is a
   cheap correction to make now.
2. **The gate governing sim mode.** Stricter than the rest of the app, where
   `FIVE12_DEVICE_SIM` works regardless of a feature gate. My reasoning: the
   Astera gate is the operator's single "leave the fixtures alone" switch, and
   a switch that still renders a populated panel is a confusing one. The cost
   is that Astera cannot be demoed with the gate off.
3. **The PIN alias.** Truncated SHA-256, 4 hex characters. Deliberately not
   presented as secrecy — a 4-digit PIN is trivially brute-forced from any
   short hash, so the protection is keeping the value out of casual view and
   logs, which is what the agreed direction asked for. The argument is in the
   docstring; disagree with it there if you disagree.

## Reviewer findings

### Critical

### Warnings

### Suggestions

### Looks good

## Next action

**Hermes:** review the diff independently, rerun the canonical checks, and
record findings in the section above (Critical / Warning / Suggestion / Looks
Good) on this file or a sibling under `reviews/`.

Do not merge to `main` without that review — rule 5, and Anthony's rig has live
Asteras on set. Integration is serial per rule 6; this branch is based on
`e3c4bb7` and will need a re-check against whatever `main` has moved to.
