# Active work — Hog fixture-library import

- **Owner:** Hermes
- **Branch:** `feat/hermes/hog-fixture-import`
- **Workspace:** persistent worktree at `/root/five12-worktrees/hermes-hog-fixture-import`
- **Base SHA:** `aa4b25b9d2411ec9565ebcb918b3e302f9883701`
- **Status:** implementation complete; ready for review/integration
- **Last updated:** 2026-07-29

## Goal

Let Anthony select ETC's official Hog 5 `summary.xml` in Five12, validate it, back up the current fixture catalog, and atomically replace that catalog with the Hog manufacturer/profile records used by the Patch picker.

## Acceptance criteria

- [x] Wrong, malformed, oversized, or unsupported XML is rejected before fixture data changes.
- [x] Every successful replacement creates a restorable database snapshot of the prior fixture rows.
- [x] Replacement is transactional: backup + delete + Hog insert either all succeed or all roll back.
- [x] A saved backup can be restored from the Five12 UI.
- [x] Imported rows preserve manufacturer, Hog UUID, footprint, revision, fixture kind, origin, and library version without inventing unsupported DMX-function data.
- [x] Patch fixture search remains responsive with the full Hog library and shows manufacturer/profile/footprint clearly.
- [x] Import is verified against official Hog 5 library `5.0.766` / `summary.xml` (29,936 records).
- [x] Backend tests, frontend tests, frontend build, migration upgrade/downgrade smoke test, and repository hygiene checks pass.

## Reserved paths

- `backend/app/models.py` (`Fixture` metadata plus fixture-backup model only)
- `backend/app/fixture_library.py`
- `backend/app/fixture_library_routes.py`
- `backend/app/routes.py` (patch-address bounds and imported-row identity handling only)
- `backend/app/__init__.py` (blueprint registration only)
- `backend/config.py` (fixture XML request-size bound only)
- `backend/run_desktop.py` (idempotent legacy SQLite schema bridge only)
- `backend/migrations/versions/*hog_fixture_library*.py`
- `backend/tests/test_fixture_library.py`
- `app/src/pages/Database.jsx`
- `app/src/pages/PatchSheet.jsx` (switch fixture fetch to the lean patch-profile endpoint only)
- `app/src/components/PatchForm.jsx`
- `app/src/components/PatchTab.jsx` (remove obsolete eager fixture prop only)
- Fixture-library frontend tests added by this task
- `docs/coordination/active/hermes--hog-fixture-import.md`

## Must-not-touch paths

- Network/IP configuration sections in `backend/app/routes.py` and `backend/tests/test_network_routes.py` (Claude PR 2 scope)
- BLE/Cintenna implementation paths
- Astera implementation paths
- Dependency manifests and lockfiles unless a verified blocker requires explicit coordination

## Interfaces and contracts

- Existing `/api/fixtures` CRUD remains compatible.
- New fixture metadata is additive and nullable for hand-entered/legacy records.
- XML import is user-selected and local; the Hog library is not bundled or redistributed in Git.
- `summary.xml` supplies catalog identity and footprint metadata only. It does not authorize Five12 to claim detailed DMX function maps.

## Dependencies and blockers

- No blocker. The official source XML has been downloaded separately for software verification and will not be committed.
- The existing active PR 2 reserves only the network section of `backend/app/routes.py`; this task avoids that file by using a separate blueprint.

## Plan or spec

- Parse and validate `http://schemav5.hogfour.com/Summary` with bounded upload size and no DTD/entity support.
- Snapshot existing fixtures into a backup table, then replace in one transaction.
- Expose list/restore backup endpoints and wire them into the fixture database page.
- Use bounded server-side manufacturer/profile search in the active PatchForm picker.

## Decisions and trade-offs

Use the existing flat `fixtures` table with additive Hog metadata rather than introducing a full normalized product/mode/part graph in this change. That makes the official profiles immediately usable by the current Patch workflow while preserving enough identifiers for a later normalized library. Compound relationships and detailed DMX functions are not represented yet and will not be guessed.

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| Official XML structure/count inspection | 519 manufacturers, 29,936 fixtures; schema and fields confirmed | software verified against official vendor artifact |
| Official XML preview/import/restore on temporary SQLite | 29,936 imported; 21,625 patchable; 8,311 unsupported; saved PatchRow survived import and restore | software verified against official vendor artifact |
| Backend `pytest -q tests` | 404 passed | software verified |
| Frontend `npm run test` | 57 passed | software verified |
| Frontend `npm run build` | passed; existing large-chunk warning only | software verified |
| Alembic upgrade/downgrade/re-upgrade with imported NULL power data | passed; downgrade intentionally maps unknown values to legacy zero | software verified |
| Temporary browser UI check | Database pagination/search and PatchForm ARRI SkyPanel search/patch completed successfully | software verified |
| Temporary MariaDB 11.4 official import/lock/backup/restore | 29,936 rows imported in 9.42 s; 16 MiB packet limit accepted 9.64 MiB snapshot; concurrent CRUD returned 409; backup download and restore passed | software verified against official vendor artifact |

## Independent review disposition

- P1 downgrade failure with unknown power data: fixed and covered by a permanent Alembic regression test.
- P1 catalog lock gap: fixture create/update/delete and Excel import now participate in the same mutation lock; final preview identity is checked inside that lock.
- P2 stale optimistic edits: fixture rows save on blur, validate HTTP responses, adopt authoritative server data, and reload after errors.
- P2 MySQL gap: verified in a disposable MariaDB 11.4 container, then removed the container and downloaded image.

## Commits

## Risks and skipped checks

- No redistribution permission has been established; Five12 therefore imports a file the operator selects and does not bundle the vendor library.
- Import/restore is software verification only until Anthony runs it in the Windows desktop application against a copy of his local database.

## Handoff / next action

Review the final diff, commit, push, and verify the remote feature branch. Do not run the import against a real user database until its path and external backup are confirmed.
