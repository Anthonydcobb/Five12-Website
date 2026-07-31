# Patch Import Fixture Matching Implementation Plan

> **For Hermes:** Implement this plan task-by-task with tests first and independent exact-head review.

**Goal:** Add an import review that identifies fixture types absent from the Five12 library, offers safe exact-footprint suggestions, supports catalog search/selection, and can create a custom fixture without silently substituting an incompatible profile.

**Architecture:** Keep file parsing and text ranking in `patch_import.py`, expose a preview endpoint and selection-aware extension to the existing commit endpoint, and build a three-step React wizard: column mapping, grouped fixture review, commit. Existing callers remain compatible because selections are optional. Matching is import-time only; no database migration or persistent fixture foreign key is introduced in this iteration.

**Tech Stack:** Flask, SQLAlchemy, pandas/openpyxl, React 19, Vitest/Testing Library.

---

### Task 1: Specify source grouping and ranking

**Objective:** Produce deterministic source signatures and ranked compatible suggestions while never suggesting a mismatched DMX footprint.

**Files:**
- Modify: `backend/app/patch_import.py`
- Test: `backend/tests/test_patch_import.py`

**Steps:**
1. Add failing tests for normalized source signatures, grouping duplicate imported types, exact-name detection, fuzzy ranking, mode-number discrimination, and channel-count exclusion.
2. Run the focused tests and confirm the new tests fail for missing functions.
3. Implement small pure helpers using normalized alphanumeric tokens and `difflib.SequenceMatcher`; require exact footprint before scoring.
4. Rerun focused tests and commit the pure matching layer.

### Task 2: Add server-side match preview and selection validation

**Objective:** Let the client request grouped suggestions and safely apply selected library profiles during commit.

**Files:**
- Modify: `backend/app/routes.py` patch-import section only
- Test: `backend/tests/test_patch_import_api.py`

**Steps:**
1. Add failing API tests for grouped match preview, exact preselection, fuzzy suggestions remaining unselected, incompatible selection rejection before writes, compatible selection substitution, unmatched preservation, and existing no-selection compatibility.
2. Run focused API tests and confirm discriminating failures.
3. Add `POST .../import/matches`, parse the same file/mapping/header tuple as commit, query patchable fixtures in bounded batches by imported channel counts, and return grouped suggestions.
4. Extend commit with optional `fixtureSelections`; validate IDs and footprints before constructing any `PatchRow`, then apply selected profile name/footprint and return match counts.
5. Rerun focused tests and commit.

### Task 3: Validate and create custom fixtures

**Objective:** Allow an unmatched group to become a manual fixture-library entry safely.

**Files:**
- Modify: `backend/app/routes.py` fixture CRUD section only
- Test: suitable focused backend route test

**Steps:**
1. Add failing tests for blank name, invalid footprint, overlong fields, optional manufacturer persistence, duplicate name/manufacturer/footprint rejection, and successful creation under the catalog mutation lock.
2. Run focused tests and confirm failures against the permissive existing endpoint.
3. Implement strict validation without changing Hog catalog identity fields; custom rows retain `librarySource = null`.
4. Rerun focused tests and commit.

### Task 4: Build the fixture review UI

**Objective:** Give Anthony a practical review table with search, profile selection, custom creation, and explicit unmatched status.

**Files:**
- Modify: `app/src/components/ImportWizard.jsx`
- Create: `app/src/components/ImportWizard.test.jsx`
- Modify: `app/src/components/PatchTab.jsx` import-result message only

**Steps:**
1. Add failing component tests for mapping-to-review transition, exact preselection, fuzzy/unmatched status, debounced or explicit catalog search, incompatible-footprint refusal, selecting another result, custom fixture creation/selection, explicit unmatched import, and commit summary.
2. Run the focused frontend tests and confirm failures.
3. Implement wizard steps `Map columns → Match fixtures → Import`, grouped by source signature so one choice applies to every identical fixture row.
4. Show original type/count permanently during review. Search `/api/fixture-library/patch-profiles`; label every candidate with manufacturer/profile/footprint. Do not auto-retry mutations.
5. Add a compact custom-fixture form with manufacturer, profile name, channel count prefilled from the imported group, and optional notes.
6. Send selections on commit and report matched/unmatched counts before reloading.
7. Rerun focused tests and commit.

### Task 5: Regression and integration verification

**Objective:** Prove the feature works without regressing fixture-library mutation safety or existing imports.

**Files:**
- Update: coordination record only unless tests find defects

**Steps:**
1. Run focused backend import tests.
2. Run the complete backend suite from repository root with the canonical app interpreter.
3. Install frontend dependencies if needed, run focused ImportWizard tests, full frontend suite, and production build.
4. Run `git diff --check`, inspect the complete diff, and verify no network/BLE, migration, model, fixture bulk-import, lockfile, or credential paths changed.
5. Update the coordination record with exact results, commit, push, and request independent exact-head review.
6. Address review findings, rerun affected checks, archive the record, and integrate only if remote `main` remains compatible.
