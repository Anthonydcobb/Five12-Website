# Active work — agent coordination

- **Owner:** Hermes
- **Branch:** `docs/hermes/agent-coordination`
- **Worktree:** `/root/five12-website`
- **Base SHA:** `c8be6db`
- **Status:** active
- **Last updated:** 2026-07-27

## Goal

Add a shared Claude Code + Hermes workflow, record Hermes's initial repository concerns, and obtain Claude Code's independent response before deciding remediation work.

## Acceptance criteria

- [x] Stable collaboration rules are documented.
- [x] Active-work and handoff templates are provided.
- [x] Initial concerns are prioritized and evidence-based.
- [ ] Claude Code response is recorded.
- [ ] Documentation is linked from both `AGENTS.md` and `CLAUDE.md`.
- [ ] Diff is verified, committed, and pushed.

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

Claude Code reviews the workflow and concerns, agrees or pushes back with evidence, then Anthony chooses the first remediation branch.
