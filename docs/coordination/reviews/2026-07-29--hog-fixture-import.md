# Review — Hog fixture-library import

- **Date:** 2026-07-29
- **Implementation branch:** `feat/hermes/hog-fixture-import`
- **Reviewer:** independent Hermes leaf agent (`deleg_bfe6fce4`)
- **Scope:** backend transaction safety, SQLite/MySQL behavior, migration downgrade, fixture semantics, React behavior, and test gaps

## Findings and disposition

### P0

None.

### P1 — migration downgrade failed after Hog import

**Finding:** Hog rows store unknown wattage and weight as `NULL`, while downgrade restored the legacy `NOT NULL` columns without converting existing data.

**Disposition:** fixed. Downgrade now explicitly maps unknown power fields to legacy zero before tightening nullability. A permanent Alembic test covers upgrade, insertion of a Hog-style row with unknown power data, downgrade, schema nullability, and resulting values.

### P1 — normal fixture writes did not participate in the catalog lock

**Finding:** create/update/delete and fixture Excel import could race catalog replacement or restore.

**Disposition:** fixed. Every fixture-catalog mutation now uses the same lock/rejection protocol. Import performs final catalog count/checksum validation after acquiring the lock. Concurrent SQLite and MariaDB CRUD attempts return HTTP 409.

### P2 — optimistic React edits could retain stale provenance or hide failures

**Disposition:** fixed. Edits are local until blur, then validate the HTTP response and replace the local row with the authoritative server row. Failure is reported and the catalog is reloaded. Editing controls are disabled while import/restore is busy.

### P2 — MySQL path was unverified

**Disposition:** verified using a disposable MariaDB 11.4 Docker container. The official 29,936-profile import completed in 9.42 seconds; all imported power metadata stayed unknown; the approximately 9.64 MiB JSON backup fit under a 16 MiB `max_allowed_packet`; advisory-lock contention returned 409; validated backup download and restore passed. The temporary container and downloaded image were removed afterward.

## Final checks

- Backend: 404 tests passed.
- Frontend: 57 tests passed.
- Frontend production build passed; existing large-chunk warning remains.
- Official temporary SQLite import/backup/restore passed.
- Official temporary MariaDB import/lock/backup/restore passed.
- Browser review passed for catalog search, PatchForm search, unknown metadata display, and a temporary ARRI SkyPanel patch row.
- Official vendor XML remains outside Git.

## Verdict

No remaining P0/P1 blockers identified. Ready for branch review and integration. Do not import into a real user database until its exact path and an external backup destination are confirmed.
