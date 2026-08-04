# Independent Review — Astera ART7 Stage A

- **Reviewer:** Hermes Agent
- **Implementation branch:** `feat/claude/astera-stage-a`
- **Implementation head reviewed:** `77d92bf`
- **Review branch:** `review/hermes/astera-stage-a`
- **Evidence level:** `simulated` — no ART7, phone, or fixture contacted
- **Review date:** 2026-08-03
- **Handoff:** `docs/coordination/reviews/2026-08-03--claude-astera-stage-a-handoff.md`

## Verification

- Frontend: `npm ci && npx vitest run` — **80 passed**.
- Frontend build: `npm run build` — **passed**. Vite emitted the repository's existing large-chunk warning.
- Backend: the canonical Astera test selection could not run in this Linux review worktree because the environment has no Python dependencies installed; collection stopped at `ModuleNotFoundError: No module named 'flask'`. Claude's Windows result is retained as owner-reported evidence, not independent Hermes verification.
- No live hardware or network acceptance test was attempted.

## Critical

_None._

## Warning

### W1 — The normalizer is not defensive against non-object payloads

`backend/app/integrations/astera.py::_normalize()` calls `.get()` on `raw_status`, `raw_targets`, and `bridge` without first validating that each is a mapping. A malformed but valid JSON response such as `null`, `[]`, or `{"bridge": []}` can therefore raise `AttributeError` after `_fetch_json()` succeeds. `get_status()` catches transport/JSON boundary errors, but not this normalization exception, allowing an unverified device response to become a backend 500.

This matters because the protocol and field names are explicitly unverified. Treat unexpected shapes as unavailable or return a structured normalization error, and add tests for null/list/non-mapping responses. Missing-key handling alone is not sufficient.

### W2 — Unknown boolean values render as known negative state

`AsteraPanel.jsx` renders `appOnline` with a truthiness check: any `null`/missing value becomes `offline`. The backend intentionally maps unverified/missing fields to `None`, so the UI can claim the AsteraNext app is offline when the response merely omitted or renamed the field. Render three states (`online`, `offline`, `unknown`) and preserve the protocol-unverified distinction.

## Suggestion

### S1 — Increase the PIN alias width or label it as a short fingerprint

`_pin_alias()` exposes only the first four hex characters of SHA-256. This is acceptable as hygiene rather than secrecy, and the raw PIN is correctly excluded from the UI/history, but the 16-bit alias can collide and falsely suggest that two PINs are the same. Use a wider deterministic alias (for example, 8 hex characters) or explicitly label it as a short fingerprint and test collision-resistant identity expectations. Do not treat the alias as authentication or secret material.

### S2 — Add a focused gate/UI test for the disabled copy

The backend gate tests are strong. Add a frontend test asserting the default/gate-off payload is presented as **disabled**, not as an unavailable device that was searched and found absent. This locks the safety-language contract at the user-facing boundary.

## Looks Good

- The gate is checked at call time, which is correct for cached adapters and prevents a stale instance from outliving an operator's environment change.
- The gate-off path is tested against DNS, TCP, and HTTP hooks; simulator behavior is explicitly covered.
- The endpoint allowlist uses keys rather than caller-supplied paths, and the implementation refuses redirects, requires JSON, caps streamed responses, and brackets IPv6 literals.
- The adapter is read-only and does not include AsteraNext's state-changing GET endpoints.
- Raw Radio PIN handling is appropriately treated as hygiene, not cryptographic protection.
- `protocolVerified: false`, simulated labeling, and the explicit BLE-vs-Classic block are correctly preserved.
- `ALL_DEVICE_IDS` gaining the Astera row is a deliberate generic-device contract change and is documented in the handoff.

## Disposition

**Review requested changes before merge:** W1 and W2 should be fixed before integration because they can turn unverified external data into misleading UI or a backend error. S1/S2 are recommended follow-ups. Stage B remains blocked pending isolated bench identification of BLE GATT versus Classic RFCOMM.
