# Active work — patch-import fixture matching

- **Owner:** Hermes
- **Branch:** `feat/hermes/patch-import-fixture-matching`
- **Workspace:** `/root/five12-worktrees/hermes-patch-import-fixture-matching`
- **Base SHA:** `57bd29bd6a6261745b42db3a8d2a0423b4e62a21`
- **Status:** active
- **Last updated:** 2026-07-31

## Goal

Add a safe fixture-matching review to patch-sheet import: rank library profiles by imported fixture name/mode text while requiring an exact DMX footprint, let the operator search and choose another profile, and let the operator create and select a custom fixture when the catalog has no match.

## Acceptance criteria

- [ ] Import mapping is followed by a fixture review grouped by unique imported fixture type and channel count.
- [ ] Exact normalized library matches may be preselected; fuzzy suggestions require operator choice.
- [ ] Suggestions and manual selections require an exact channel count when the sheet provides one.
- [ ] The operator can search the patchable fixture catalog and choose a different compatible profile.
- [ ] The operator can create a validated custom fixture and immediately select it.
- [ ] Unmatched imported types remain visibly identified and can be intentionally imported unchanged.
- [ ] Commit validates all client selections server-side and returns matched/unmatched counts.
- [ ] Existing import behavior remains compatible when no selections are supplied.
- [ ] Focused backend/frontend tests, complete suites, build, and diff checks pass.
- [ ] Independent exact-head review has no Critical or Warning findings before integration.

## Reserved paths

- `backend/app/patch_import.py`
- `backend/app/routes.py` — fixture CRUD and patch-import sections only; do not touch Claude's reserved network section
- `backend/tests/test_patch_import.py`
- `backend/tests/test_patch_import_api.py`
- focused fixture-create tests if needed
- `app/src/components/ImportWizard.jsx`
- `app/src/components/ImportWizard.test.jsx`
- `app/src/components/PatchTab.jsx` — import completion message only
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
| pending | pending | software verification |

## Commits

## Risks and skipped checks

No fixture profile is silently substituted on fuzzy similarity. Mode is embedded in Hog profile names rather than stored as a separate field, so similarity ranks text but exact footprint remains the safety boundary.

## Handoff / next action

Implement test-first, verify, push, and request independent exact-head review.
