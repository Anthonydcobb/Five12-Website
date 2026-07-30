# Active work — Five12 runtime and desktop hardening plan

- **Owner:** Hermes
- **Branch:** `docs/hermes/runtime-hardening-plan`
- **Workspace:** `/root/five12-worktrees/hermes-runtime-hardening-plan`
- **Base SHA:** `aa4b25b9d2411ec9565ebcb918b3e302f9883701`
- **Status:** review requested from Claude
- **Last updated:** 2026-07-30

## Goal

Publish the detailed runtime/desktop hardening execution plan and the proposed Claude + Hermes owner/reviewer protocol so Claude can review a durable Git artifact.

## Detailed plan

`docs/superpowers/plans/2026-07-30-five12-runtime-desktop-hardening.md`

## Review request

Claude Code: review the complete plan read-only before implementing application code. Follow the prompt in section 8.8. Check current `origin/main`, all active coordination records, existing local/unpublished Claude branches, dependency order, reservations, safety boundaries, and practical owner/reviewer split. Save findings under `docs/coordination/reviews/` on a dedicated `docs/claude/<slug>` branch and return the branch name plus full commit SHA.

## Reserved paths

- `docs/superpowers/plans/2026-07-30-five12-runtime-desktop-hardening.md`
- `docs/coordination/active/hermes--runtime-hardening-plan.md`

## Must-not-touch paths

- Application source
- Migrations
- Dependency manifests and lockfiles
- Credentials and `.env` files

## Acceptance criteria

- [x] Detailed execution plan is stored at the repository's canonical plan location.
- [x] Claude/Hermes roles, handoffs, parallelism rules, and review protocol are included.
- [x] Claude has a ready-to-paste first-pass review prompt.
- [ ] Claude review branch and pinned SHA received.
- [ ] Hermes reconciles verified findings into the plan.

## Checks run

- Markdown readback and Git diff checks only; this documentation branch changes no application behavior.

## Evidence level

Software/documentation verification only. No Windows bench or actual lighting hardware verification was performed.
