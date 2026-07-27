# Five12 Agent Coordination

This folder is the shared coordination layer for Anthony, Claude Code, and Hermes Agent.
It complements detailed implementation plans in `docs/superpowers/`; it does not replace them.

## Non-negotiable operating rules

1. **`main` is integration-only.** Agents work on branches and do not commit directly to `main`.
2. **Use isolated worktrees for concurrent work.** The stable checkout is for review/integration; each feature gets its own worktree.
3. **Claim scope before editing.** Create one file in `docs/coordination/active/` and list the exact reserved paths, shared contracts, and files that must not be touched.
4. **One owner per collision-prone path.** Do not concurrently edit migrations, lockfiles, agent instructions, API contracts, `backend/app/models.py`, `backend/app/routes.py`, or other shared central files.
5. **Separate implementation from review.** When both agents contribute to one feature, one implements and the other independently reviews and verifies. Do not silently replace the other agent's work.
6. **Integrate serially.** Merge the foundational or lower-risk branch first; rebase the second branch onto the new `main`, resolve conflicts in its worktree, and rerun all checks.
7. **Record decisions, not private reasoning.** Summarize evidence, trade-offs, rejected options, and the chosen path. Do not dump hidden chain-of-thought.
8. **Evidence labels are required.** Hardware behavior must be labeled `simulated`, `bench-tested`, or `verified on actual gear`.
9. **No invented lighting data.** Fixture modes, DMX footprints, protocol fields, console operations, and vendor commands require an official source or Anthony's confirmation.
10. **No unverified live writes.** New device/network integrations start read-only. Writes require an explicit allowlist, confirmation, validation, acknowledgement, and readback where meaningful.
11. **Keep the local safety boundary.** The unauthenticated backend must remain bound to loopback. Any LAN/hosted exposure requires an authentication and authorization design first.
12. **Never commit secrets.** Use `.env.example` with placeholders. Credentials, tokens, linking keys, and private keys stay out of Git and logs.
13. **Protect show data.** Destructive and bulk actions need confirmation, clear error reporting, transaction safety, and a backup/rollback path where practical.
14. **Verify before handoff.** Report the real commands run and their results. Never report an unrun check as passing.

## Branch and worktree convention

Branches use `<type>/<agent>/<slug>`:

```text
feat/claude/patch-history
fix/hermes/import-validation
docs/hermes/agent-coordination
```

Suggested sibling worktrees:

```text
Five12-TheApp/                  # stable integration checkout
Five12-worktrees/claude-<slug>/
Five12-worktrees/hermes-<slug>/
```

Do not merge one feature branch into another. If a feature depends on another branch, merge the prerequisite to `main` first.

## Starting work

1. Fetch and start from current `origin/main`.
2. Create a dedicated branch and worktree.
3. Copy `templates/active-work.md` into `active/<agent>--<slug>.md`.
4. Record owner, base SHA, scope, reserved paths, contracts, acceptance criteria, and required checks.
5. If another active file reserves a needed path, stop and coordinate before editing.

## During work

- Commit small logical changes using conventional subjects such as `feat:`, `fix:`, `test:`, `docs:`, and `chore:`.
- Update the active note when scope, interfaces, migrations, dependencies, or risks change.
- Keep detailed feature plans in `docs/superpowers/plans/` and link them from the active note.
- Put durable architecture choices in `decisions/` only when they affect future features.
- Do not put temporary logs, raw credentials, live tokens, packet captures, or generated build output in this folder.

## Handoff and review

Before review, the owner records:

- Commits and changed paths
- API/schema/migration/dependency changes
- Commands run and exact outcomes
- Hardware evidence level
- Known risks and skipped checks
- Clear next action

The reviewer checks the diff independently, reruns canonical checks, and writes findings under `reviews/` using Critical / Warning / Suggestion / Looks Good.

## Current canonical checks

Until CI provides a single command, use the applicable checks:

```bash
# Backend, from repository root
.venv/bin/python -m pytest -q backend/tests

# Frontend
cd app
npm ci
npm run test   # when the branch provides the test script
npm run build

# Repository hygiene
git status --short
git diff --check
git ls-files | grep -E '(^|/)(\.env|__pycache__|.*\.pyc)$'  # should return nothing after cleanup
```

Hardware-dependent acceptance tests remain separate and must identify the actual device/firmware without storing credentials or linking keys.

## Folder layout

```text
docs/coordination/
├── README.md
├── active/       # one conflict-resistant file per agent/task
├── plans/        # lightweight cross-agent plans; link detailed superpowers plans
├── decisions/    # durable architecture and workflow decisions
├── reviews/      # independent reviews and responses
├── templates/    # active-work and handoff templates
└── archive/      # completed active notes and handoffs
```

When work merges, move its active note to `archive/`, retain useful verification evidence, remove the worktree, and prune the branch.
