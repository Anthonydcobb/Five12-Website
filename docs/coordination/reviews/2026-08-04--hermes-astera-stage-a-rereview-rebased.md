# Independent Re-review — Astera Stage A (rebased tree)

- **Reviewer:** Hermes Agent
- **Implementation branch:** `feat/claude/astera-stage-a`
- **Branch head reviewed:** `fcd9fcd`
- **Exact fix commit requested by Claude:** `8db6c9b`
- **Base:** `origin/main` at `5109edb`
- **Disposition:** **Approved for merge**

## Scope

This is a fresh re-review after Claude rebased the Astera branch onto current `main` and remapped the earlier SHAs. The prior approval of `fcdb77c` is superseded by this review; the actual target here is `8db6c9b` in the rebased tree.

## Findings

### W1 — malformed payload handling: fixed

`get_status()` now rejects non-object top-level JSON for both `/api/status` and `/api/targets` with an unavailable response and an explicit reason. `_normalize()` now separately guards the nested `bridge` mapping and `targets` list. Non-dictionary target entries are skipped safely. The new tests cover `null`, arrays, strings, numbers, malformed nested bridge data, malformed target lists, and mixed target entries.

No remaining crash path was found in the reviewed normalization boundary.

### W2 — online/offline/unknown mapping: fixed

The frontend uses an explicit three-state mapping:

- `true` → `online`
- `false` → `offline`
- `null`, missing, or other values → `unknown`

The frontend tests independently verify both real `false` → `offline` and `null` → `unknown`.

### Disabled payload flag: accepted

The additive Astera-only `disabled: true` flag is appropriate because gate-off means no lookup occurred, while `available: false` without the flag means a real lookup failed. The panel uses the flag to render `not searched for` rather than `device unavailable`. The backend and frontend tests cover both states.

I do not require other adapters to adopt this field in this change. If a common device-status contract is desired later, it should be designed and migrated separately rather than making unrelated adapters change opportunistically.

### S1/S2: fixed

The PIN alias is widened to eight hexadecimal characters, and the disabled-state copy is contract-driven and tested.

## Verification

Performed from a fresh detached worktree at `origin/feat/claude/astera-stage-a` (`fcd9fcd`):

```text
python3 -m pytest -q backend/tests
617 passed, 19 warnings in 57.37s

cd app && npm ci && npx vitest run && npm run build
85 passed across 8 test files
production build passed
```

`git diff --check origin/main..HEAD` passed with no output and the worktree was clean after verification.

The repository still does not contain `backend/requirements-dev.txt`; therefore that exact two-file install command remains unavailable. The available runtime requirements were already installed in the review environment, and the complete backend suite executed successfully. This is not an owner-reported-only result.

The warnings were existing dependency/runtime warnings: one coroutine resource warning, SQLAlchemy legacy-query warnings, and an Alembic `get_engine` deprecation warning. The frontend build emitted the existing large-chunk warning.

## Boundaries

This approves the software merge only. Stage A remains gated, read-only, and protocol-unverified. No direct ART7 Bluetooth/fixture control is authorized, and the feature gate remains off by default.
