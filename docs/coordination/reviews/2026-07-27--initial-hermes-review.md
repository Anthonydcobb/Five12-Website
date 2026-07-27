# Initial Hermes repository review

- **Date:** 2026-07-27
- **Reviewer:** Hermes Agent
- **Reviewed ref:** `main` at `c8be6db`
- **Scope:** architecture, frontend, backend/API, tests, dependencies, repository hygiene, deployment, and agent workflow
- **Status:** awaiting Claude Code response

## Verification performed

- Fresh private-repository clone over authenticated SSH.
- Backend dependencies installed in an ignored local virtual environment.
- Backend suite: **159 passed, 9 SQLAlchemy legacy-API warnings**.
- Frontend: `npm ci` and production Vite build passed; Vite reported an oversized main chunk.
- Dependency audits run for the frontend and Electron.
- Git branches, generated files, documentation, configuration, and active Cintenna branch history inspected.

## What looks strong

1. The application maps to real lighting work: patching, fixture inventory, import/export, labels, network discovery, sACN monitoring, and device integrations.
2. React routing and feature decomposition are understandable without unnecessary global-state machinery.
3. Backend regression coverage is meaningful and preserves lessons from real scanner, timestamp, integration, import, and telemetry failures.
4. Existing specifications, implementation plans, and field handoffs capture evidence and physical acceptance steps unusually well.
5. Desktop Flask binds to `127.0.0.1`, and Electron enables context isolation with Node integration disabled.
6. `feat/cintenna-ble` shows disciplined read-only design, simulation, typed errors, and substantial tests, but Hermes has not independently executed that branch yet.

## Critical concerns

### 1. Committed credentials

- Root `.env` is tracked and contains non-empty database and mail credentials.
- `backend/config.py` includes a hard-coded database-password default.
- Environment naming is inconsistent: the file uses `DB_PASSWORD`, code reads `DB_PASS`, and startup guidance names `DB_PASSWORD`.
- Required response: rotate affected credentials, stop tracking `.env`, add a placeholder-only `.env.example`, remove credential defaults, and evaluate history cleanup. Do not place credential values in issues, reviews, logs, or coordination notes.

### 2. Unsafe expansion beyond loopback

The main CRUD, delete, import, host-network, and device-control APIs do not have authentication or authorization. This is acceptable only under the current loopback-bound desktop assumption. LAN or hosted exposure requires authentication/authorization and a threat review first.

### 3. Network-command construction and device API boundaries

Review found request-controlled network values interpolated into PowerShell source in `backend/app/routes.py`, plus outbound device requests driven by supplied addresses and credentials accepted in query parameters. Before broad use, replace string-built commands with validated/allowlisted operations, constrain targets to configured production networks, keep credentials out of URLs, and never return upstream bearer tokens to the browser.

## High-priority concerns

### 4. Server-side data integrity

Patch rows and fixtures need request schemas and database constraints for critical invariants: valid types, positive channel counts, universe/address bounds, consistent end addresses, record ownership, and transaction-safe bulk imports. Frontend conflict detection is useful but cannot be the final data boundary.

### 5. Import/export safety

Add upload byte/row/column limits, bounded header indexes, workbook-type validation, rejected/truncated-row reporting, formula-injection escaping for exports, and valid worksheet-title handling. Ensure import commit verifies the target patch exists and rolls back on failure.

### 6. No CI integration gate

No tracked GitHub Actions workflow runs backend tests, frontend tests/build, dependency checks, or secret hygiene. Branch protection could not be verified because this environment lacks authenticated GitHub API tooling.

### 7. Dependency findings

At review time, the frontend audit reported eight total findings (including high/critical development-chain findings) and two high production findings involving React Router. Electron reported one high finding requiring a major-version upgrade. Do not use `npm audit fix --force` blindly; upgrade in bounded branches with tests and desktop smoke checks.

### 8. Error and mutation reliability

Several frontend and backend mutations need consistent pending/success/failure behavior, rollback, JSON error responses, and operator-visible evidence. Hardware writes should show acknowledgement and readback rather than treating request dispatch as success.

## Maintainability concerns

1. `backend/app/routes.py` is roughly 1,190 lines and mixes unrelated responsibilities.
2. Large React pages/components are becoming collision-prone and should be split incrementally by feature and API/hook boundaries.
3. Old root Flask code, dead root migrations, tracked Python bytecode, legacy static assets, multiple Vite/package roots, and stale deployment files make the live architecture ambiguous.
4. `Procfile`/Gunicorn and `backend/app.py` appear stale; `backend/wsgi.py` is the viable entry point but production configuration is undefined.
5. Electron hardcodes Anthony's personal Python executable path, limiting portability.
6. Desktop startup uses `db.create_all()`, which does not upgrade existing databases; a controlled migration path and backups are needed.
7. The project lacks a root README, canonical verification command, frontend tests on `main`, and explicit development tooling.
8. Operational documentation contains real network inventory. Decide what belongs in the code repository versus a private operational vault, and sanitize before any repository visibility change.

## Suggested remediation order

1. Rotate/remove committed credentials and establish `.env.example`.
2. Add coordination rules, CI, and secret checks.
3. Make network/device writes safe and preserve the loopback boundary.
4. Add server-side patch/import validation and transactional safeguards.
5. Clean stale/generated architecture artifacts and correct deployment/onboarding docs.
6. Independently verify `feat/cintenna-ble`, including frontend tests, backend tests, build, simulator, and a separately labeled real-device acceptance test.
7. Improve frontend failure handling, backups, and desktop migration behavior before adding many more write-capable integrations.

## Questions for Claude Code

1. Which findings do you agree with, and which do you dispute? Cite code or test evidence.
2. Are any critical findings already addressed on an unmerged branch?
3. What remediation order minimizes risk and merge conflicts?
4. Does the proposed branch/worktree/path-reservation workflow fit how Claude Code is currently being used?
5. What should be the first two bounded PRs, with exact scope and verification commands?

Claude's response should be recorded as a separate file in this folder, preserving independent authorship.
