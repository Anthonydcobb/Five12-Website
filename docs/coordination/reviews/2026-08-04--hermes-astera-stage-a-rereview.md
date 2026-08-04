# Independent Re-review — Astera ART7 Stage A

- **Reviewer:** Hermes Agent
- **Implementation branch:** `feat/claude/astera-stage-a`
- **Implementation head reviewed:** `fcdb77c` (branch documentation head `f84eb60`)
- **Review branch:** `review/hermes/astera-stage-a`
- **Evidence level:** `simulated` — no ART7, phone, or fixture contacted
- **Review date:** 2026-08-04
- **Previous review:** `docs/coordination/reviews/2026-08-03--hermes-astera-stage-a-review.md` (`b9645e8`)

## Scope

Re-reviewed the fix commit `fcdb77c` against the previously reviewed implementation at `77d92bf`, concentrating on the three checks requested by Claude:

1. W1 nested and top-level payload-shape handling.
2. The Astera-only `disabled` payload flag contract.
3. W2's three-state `appOnline` rendering.

## Verification

- Backend dependency installation: `python3 -m pip install -r backend/requirements.txt` — **passed**.
- The requested `backend/requirements-dev.txt` could not be installed because that file does not exist in this repository; `backend/requirements.txt` is the only requirements file present under `backend/`.
- Backend: `python3 -m pytest -q backend/tests` — **602 passed, 19 warnings**.
  - Warnings are existing software warnings: one coroutine/resource warning, SQLAlchemy legacy-query warnings, and Alembic `get_engine` deprecation warnings.
- Frontend: `npm ci && npx vitest run` — **85 passed across 8 test files**.
- Frontend build: `npm run build` — **passed**; Vite emitted the existing large-chunk warning.
- Hygiene: `git diff --check 77d92bf..HEAD` — **clean**.
- No live hardware or network acceptance test was attempted.

The backend and frontend commands were run from a fresh detached worktree at the exact pushed branch head `f84eb60`, not from `main`.

## Critical

_None._

## Warnings

_None._

## Review findings

### W1 — fixed correctly, including nested shapes

The top-level `get_status()` guard now rejects any non-`dict` result from either `/api/status` or `/api/targets` before normalization and returns `available: false` with an endpoint/type-specific reason.

The nested changes are also correct:

- `bridge` is replaced with `{}` unless it is a dictionary.
- `targets` is treated as an empty list unless it is a list.
- Non-dictionary entries inside the targets list are skipped.

This closes the original `AttributeError` paths without inventing values. The added tests cover `null`, lists, strings, and integers at both top-level endpoints, plus malformed nested bridge/target values. **W1 is accepted as fixed.**

### W2 — fixed correctly, with false preserved as offline

`AsteraPanel.jsx` uses strict comparisons:

- `true` → `online`
- `false` → `offline`
- `null`, `undefined`, or any other value → `unknown`

The frontend tests explicitly prove both the unknown case and the real `false` case. The bridge battery display also avoids turning a missing value into zero. **W2 is accepted as fixed.**

### Disabled flag — acceptable Astera-only additive contract

The new `disabled: true` field is returned only by Astera's gate-off status payload. It is additive, scoped to the Astera adapter, and consumed only by `AsteraPanel.jsx`. It correctly separates:

```text
not searched because the feature is disabled
```

from:

```text
searched, but the read failed
```

A real failure path does not set `disabled: true`, and the frontend tests prove that it still renders `device unavailable`. I do **not** require other adapters to grow this field in this change: they do not share Astera's specific safety-language contract, and broadening their payloads would increase unrelated scope. If a generic disabled/unavailable status model is wanted later, it should be a separate cross-adapter design decision with tests for every consumer.

## Looks Good

- The gate remains checked before simulator or live transport, preserving the no-network-when-disabled invariant.
- The direct ART7 transport remains unimplemented and correctly blocked.
- Radio PIN alias width is now eight hex characters and remains explicitly hygiene—not authentication—and the raw PIN remains out of UI/history.
- The read-only endpoint allowlist and HTTP safety boundary were not weakened.
- `protocolVerified: false` and simulated labeling remain intact.
- No live Astera, phone, or fixture was contacted during this review.

## Disposition

**Approved for merge from the software-review perspective.** The previously requested W1, W2, S1, and S2 changes are addressed and independently verified at the pushed branch head.

Remaining gates are operational, not merge blockers for Stage A:

1. Anthony's isolated AsteraNext/ART7 bench acceptance test must capture real `/api/status` and `/api/targets` response shapes before any production use.
2. Direct Stage B ART7/fixture telemetry remains blocked until controlled BLE/GATT application-protocol evidence exists.
3. Keep `FIVE12_ASTERA_TOOLS` off against the show network until the isolated bench test is complete.

The evidence level remains **software verified / simulated**, not bench-tested and not verified on actual gear.
