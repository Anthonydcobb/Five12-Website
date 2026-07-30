# Active work — fixture-library network error recovery

- **Owner:** Hermes
- **Branch:** `fix/hermes/fixture-network-errors`
- **Workspace:** `/root/five12-worktrees/hermes-fixture-network-errors`
- **Base SHA:** `e6ef309827b558bf1ffb03ab3984ea8235ba3477` (`origin/main`)
- **Status:** review
- **Last updated:** 2026-07-30

## Goal

Make the Database page identify the fixture-library request that failed, distinguish transport failures from HTTP errors, offer an explicit retry, clear recovered load failures, and preserve successful import/restore messages when only the follow-up refresh fails.

## Acceptance criteria

- [x] Initial catalog and metadata failures identify the affected request instead of showing only the browser's generic `NetworkError` text.
- [x] Transport failures explain that Flask/backend connectivity should be checked.
- [x] The page offers a retry action and removes each load warning after that scope recovers.
- [x] A successful import/restore remains reported as successful if a follow-up read fails.
- [x] Existing fixture import, restore, edit, search, and backup tests remain green.
- [x] Frontend test suite and production build pass.

## Reserved paths

- `app/src/pages/Database.jsx`
- `app/src/pages/Database.test.jsx`
- `docs/coordination/active/hermes--fixture-network-errors.md`

The earlier `hermes--hog-fixture-import.md` record reserved the two Database paths for the now-merged importer. This task is the same owner's explicit follow-up and supersedes that stale post-merge reservation for these two files.

## Must-not-touch paths

- Backend API, models, migrations, database data, network/BLE/sACN runtime paths
- Dependency manifests and lockfiles
- Electron/desktop runtime

## Interfaces and contracts

No API contract changes. Successful HTTP responses remain any `2xx` response (`Response.ok`), including the import route's `201 Created`.

## Dependencies and blockers

None. Anthony reproduced a real browser fetch failure, while direct and Vite-proxied status, backup, catalog, and 13.8 MB preview requests later returned 200. The UI currently conflates all load failures into one sticky generic message.

## Decisions and trade-offs

Keep action results separate from background-load failures. Track catalog and metadata load failures independently so one successful request cannot incorrectly clear an unrelated failure, while a successful retry can clear the recovered scope.

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| `npm run test -- --run src/pages/Database.test.jsx` | **6 passed**; the two new tests were first observed failing against the old UI | software verification |
| `npm run test` | **59 passed** | software verification |
| `npm run build` | passed; pre-existing large-chunk warning only | software verification |
| `git diff --check` | clean | software verification |

## Commits

Pending review commit.

## Risks and skipped checks

Browser recovery will be test-driven in jsdom and built locally. Anthony's live Windows browser remains the final bench check.

## Handoff / next action

Implement test-first, run focused/full frontend checks, then request independent review before integration.
