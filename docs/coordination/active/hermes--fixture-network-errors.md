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
| `npm run test -- --run src/pages/Database.test.jsx` | **9 passed**; the original two recovery tests and the later stale-retry race test were each first observed failing against the prior implementation | software verification |
| `npm run test` | **62 passed** | software verification |
| `npm run build` | passed; pre-existing large-chunk warning only | software verification |
| `git diff --check` | clean | software verification |

## Independent review

The first review of `d9df00a` found one Warning: overlapping retries or a search started during a retry could complete out of order and let stale data/error state overwrite a newer success. Addressed test-first with per-scope request generations, latest-request-only state commits, latest-request-only loading state, and a disabled/in-progress retry button. Added explicit regression coverage for a pending retry followed by a newer search, HTTP-vs-transport formatting, and restore-success preservation.

## Commits

- `d9df00a` — `fix: make fixture load errors actionable`
- `51d970a` — `fix: ignore stale fixture refresh results`

## Risks and skipped checks

Browser recovery will be test-driven in jsdom and built locally. Anthony's live Windows browser remains the final bench check.

## Handoff / next action

Implement test-first, run focused/full frontend checks, then request independent review before integration.
