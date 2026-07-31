# Active work — patch-import fixture matching

- **Owner:** Hermes
- **Branch:** `feat/hermes/patch-import-fixture-matching`
- **Workspace:** `/root/five12-worktrees/hermes-patch-import-fixture-matching`
- **Base SHA:** `57bd29bd6a6261745b42db3a8d2a0423b4e62a21`
- **Status:** completed; accepted for integration
- **Last updated:** 2026-07-31

## Goal

Add a safe fixture-matching review to patch-sheet import: rank library profiles by imported fixture name/mode text while requiring an exact DMX footprint, let the operator search and choose another profile, and let the operator create and select a custom fixture when the catalog has no match.

## Acceptance criteria

- [x] Import mapping is followed by a fixture review grouped by unique imported fixture type and channel count.
- [x] Exact normalized library matches may be preselected; fuzzy suggestions require operator choice.
- [x] Suggestions and manual selections require an exact channel count when the sheet provides one.
- [x] The operator can search the patchable fixture catalog and choose a different compatible profile.
- [x] The operator can create a validated custom fixture and immediately select it.
- [x] Unmatched imported types remain visibly identified and can be intentionally imported unchanged.
- [x] Commit validates all client selections server-side and returns matched/unmatched counts.
- [x] Existing import behavior remains compatible when no selections are supplied.
- [x] Focused backend/frontend tests, complete suites, build, and diff checks pass.
- [x] Independent exact-head review has no Critical or Warning findings before integration.

## Reserved paths

- `backend/app/patch_import.py`
- `backend/app/routes.py` — fixture CRUD and patch-import sections only; do not touch Claude's reserved network section
- `backend/app/fixture_library_routes.py` — patch-profile search filtering only
- `backend/app/models.py` — imported fixture source identity fields only
- `backend/migrations/versions/f12patchsrc1_preserve_imported_fixture_identity.py`
- `backend/tests/test_patch_import.py`
- `backend/tests/test_patch_import_api.py`
- `backend/tests/test_patch_profile_search.py`
- focused fixture-create tests if needed
- `app/src/components/ImportWizard.jsx`
- `app/src/components/ImportWizard.test.jsx`
- `app/src/components/PatchTab.jsx` — import completion message and original-source display only
- `app/src/components/PatchTab.test.jsx`
- `app/src/pages/Database.jsx` — preserve the existing add-blank-draft workflow explicitly
- `app/src/pages/Database.test.jsx` if focused regression coverage is needed
- this active record and linked plan

## Must-not-touch paths

- Network/BLE/scanner/sACN code
- `backend/app/models.py` and migrations; this iteration does not add durable foreign keys
- fixture-library bulk import/restore/checksum implementation
- dependency manifests and lockfiles
- credentials or environment files

## Interfaces and contracts

- New `POST /api/patch-sheets/<id>/import/matches` analyzes the mapped file and returns grouped source signatures plus exact-footprint suggestions.
- Existing `POST .../import/commit` accepts optional `fixtureSelections` keyed by server-issued source signature. A selected fixture ID is revalidated as patchable and footprint-compatible before any rows are written.
- Existing clients omitting `fixtureSelections` retain current import behavior.
- `POST /api/fixtures` gains strict custom-fixture validation and optional manufacturer support; it remains serialized by the fixture catalog mutation lock.

## Dependencies and blockers

The active PR2 record reserves only the network section of `backend/app/routes.py`; this task is disjoint and explicitly must not edit that section. No other active task reserves the frontend import wizard or patch-import helpers/tests.

## Plan or spec

- `docs/superpowers/plans/2026-07-31-patch-import-fixture-matching.md`

## Decisions and trade-offs

This first iteration keeps matching as an import-time review instead of adding a `PatchRow` foreign key. Fixture catalogs are destructively replaceable, so an ID link would need explicit replacement semantics and desktop/MySQL migration work. The importer preserves current unmatched-row behavior and reports unmatched counts; durable post-import linkage can be designed separately without blocking the requested safe review/search/create workflow.

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| `/root/five12-website/.venv/bin/python -m pytest -q backend/tests` | `546 passed, 19 warnings` | software verification |
| `npm test` | `74 passed` | software verification |
| `npm run build` | passed; existing chunk-size warning only | software verification |
| focused backend patch/custom/search tests | `62 passed` after review hardening | software verification |
| focused `ImportWizard.test.jsx` | `9 passed` after review hardening | software verification |
| focused `PatchTab.test.jsx` | `2 passed`; imported identity display and focus restoration | software verification |
| disposable SQLite Alembic upgrade/downgrade | `f12hoglib001 -> f12patchsrc1 -> f12hoglib001` passed; source identity is SQL `TEXT` | migration verification |
| isolated Flask/Vite import bench | preview/review UI exercised; commit API inserted 3 matched rows with correct end addresses | software verification |
| `git diff --check` | clean before hardening commit | software verification |

## Commits

- Accepted code head: `afc5f6af2427ba28e2a434209aa2c5263bdc0dcd`
- Independent exact-head gate: no Critical, Warning, or Suggestion findings.

## Risks and skipped checks

No fixture profile is silently substituted on fuzzy similarity. Mode is embedded in Hog profile names rather than stored as a separate field, so similarity ranks text but exact footprint remains the safety boundary.

Review iterations found missing-footprint selection, fractional-count and ID coercion, stale searches, unsafe duplicate recovery, real search limitations, punctuation-sensitive identity collisions, dismissible or competing mutations, source-identity truncation, mapping/review races, unbound catalog-profile identities, binary-float precision loss, and a catalog-mutation race after token validation. All are resolved on the current branch: imported counts use exact decimal parsing; missing or malformed footprints cannot select a profile; selected IDs are bound to digests of the reviewed profile identity and footprint; the shared cross-process catalog lock is acquired before any session read and held through patch-row commit, preventing stale MySQL `REPEATABLE READ` snapshots; custom footprint drift is rejected; stale searches are invalidated; duplicate recovery cannot choose an internal part; search is token-aware; group keys and exact matches preserve punctuation while fuzzy ranking remains loose; mappings and workflow mutations are locked appropriately; commit enforces exact source-group keys; and full imported identity is stored as SQL `TEXT`. These safety boundaries have backend and frontend regressions, and asynchronous group errors use alert semantics.

## Handoff / next action

Accepted for integration after the exact-head gate. On the Windows checkout after the `main` merge, pull `main`, run the Alembic upgrade, and browser-test import review, explicit unmatched import, manual compatible-profile selection, and custom-fixture creation on a disposable patch sheet.
