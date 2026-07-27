# Decision: Claude Code and Hermes collaboration model

- **Date:** 2026-07-27
- **Status:** accepted by Anthony
- **Decision owner:** Anthony Cobb

## Context

Five12 is growing across patching, labels, show networking, telemetry, and hardware integrations. Claude Code and Hermes Agent will both contribute. Shared checkouts and informal handoffs would create overlapping edits, stale assumptions, and difficult merges—especially around central routes, models, migrations, and lockfiles.

## Decision

Use separate branches and worktrees with explicit path ownership. For unrelated features, each agent owns a separate branch and pull request. For the same feature, one agent implements and the other independently reviews and verifies. Integrate branches serially through `main`.

The coordination record lives in `docs/coordination/`. Detailed feature implementation plans may remain in `docs/superpowers/plans/` and are linked rather than duplicated.

## Branch convention

`<type>/<agent>/<slug>`, for example `feat/claude/cintenna-status` or `fix/hermes/import-validation`.

## Collision prevention

Each active task reserves paths in its own file under `docs/coordination/active/`. A second agent must not modify a reserved path without an explicit handoff. Migrations, dependency lockfiles, central models/routes, and agent guidance receive one owner at a time.

## Merge gate

Applicable automated checks must pass; hardware behavior must carry an evidence label; security and destructive-action concerns must be resolved or explicitly accepted; the reviewing agent records findings before merge.

## Consequences

- Some work waits for a shared contract or foundational branch to merge.
- Coordination files add small overhead.
- Changes remain reviewable, ownership is visible, and agent-generated code receives independent verification.
