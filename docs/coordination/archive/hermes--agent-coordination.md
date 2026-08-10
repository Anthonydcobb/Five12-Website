# Active work — agent coordination

- **Owner:** Hermes
- **Branch:** `docs/hermes/agent-coordination`
- **Workspace:** persistent Hermes checkout at `/root/five12-website`
- **Base SHA:** `c8be6db`
- **Status:** review
- **Last updated:** 2026-07-27

## Goal

Add a shared Claude Code + Hermes workflow, record Hermes's initial repository concerns, and obtain Claude Code's independent response before deciding remediation work.

## Review request

Claude Code: read `docs/coordination/reviews/2026-07-27--initial-hermes-review.md`, answer the five questions at the end with code/test evidence, and save the response as a separate file under `docs/coordination/reviews/`. Do not modify application code in this documentation branch.

## Acceptance criteria

- [x] Stable collaboration rules are documented.
- [x] Active-work and handoff templates are provided.
- [x] Initial concerns are prioritized and evidence-based.
- [x] Claude Code response is recorded.
- [x] Hermes reviewed Claude's response and updated runtime-specific workflow rules.
- [x] Documentation is linked from both `AGENTS.md` and `CLAUDE.md`.
- [ ] Anthony selects/assigns the first two remediation PRs.
- [ ] Documentation branch is merged.

## Reserved paths

- `AGENTS.md`
- `CLAUDE.md`
- `docs/coordination/`

## Must-not-touch paths

- Application source
- Migrations
- Dependency manifests and lockfiles
- Root `.env` and credentials

## Interfaces and contracts

This branch defines collaboration process only. It makes no application-code, schema, network, or hardware behavior changes.

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| Backend pytest on base `main` | 159 passed, 9 warnings | software verification |
| Frontend production build on base `main` | passed; large chunk warning | software verification |
| npm audit on base `main` | unresolved findings recorded in review | software verification |

## Risks and skipped checks

The active `feat/cintenna-ble` branch has not yet been independently executed by Hermes. It is not declared merge-ready by this note.

## Handoff / next action

Anthony selects ownership for the first two remediation PRs: credential/config cleanup and network-route command safety. The documentation branch can then merge, and each implementation starts from updated `origin/main` with separate advisory path reservations.
