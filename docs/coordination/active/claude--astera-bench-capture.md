# Active work — astera-bench-capture

- **Owner:** Claude
- **Branch:** `docs/claude/astera-bench-capture`
- **Workspace:** `C:\dev\five12-wt\astera-bench-plan`
- **Base SHA:** `8ba2457`
- **Status:** planned
- **Last updated:** 2026-08-04

## Goal

Plan the bench session that verifies the AsteraNext HTTP protocol against real
hardware, so Stage A's `_normalize()` field mapping stops being a static-analysis
hypothesis, and so the ART7's radio transport is named for the Stage B go/no-go.

This branch adds the plan only. No capture has been run and no code changes.

## Acceptance criteria

- [x] Plan written and linked from this note
- [ ] Session 1 run; sanitized captures produced
- [ ] `_normalize()` corrected against real payloads
- [ ] `VERIFIED_AGAINST_UNIT` decided — flipped only if every mapped field confirmed
- [ ] `docs/hardware-tests/astera-art7-stage-a.md` written
- [ ] Independent review per rule 5

## Reserved paths

- `docs/superpowers/plans/2026-08-04-astera-art7-bench-capture.md`

Reserved only when the session actually runs (not claimed by this branch yet):

- `backend/app/integrations/astera.py`
- `backend/tests/test_astera_normalize.py`
- `backend/tests/fixtures/astera/`
- `docs/hardware-tests/`

## Must-not-touch paths

- Everything else. This branch is documentation only.

## Interfaces and contracts

None changed. The follow-up work changes the normalized Astera device-status
contract (`get_status()` payload), which the Devices panel consumes — that is a
contract change and needs the handoff, not this branch.

## Dependencies and blockers

- Physical access to an ART7 + dummy fixtures on an isolated network.
- KB spec §6.4 (sanitization) and §10.3 (transport truth table) are not checked
  out locally; the plan reconstructs them from the review's summary and flags
  this. Re-read them from `anthonydcobb/hermes-lighting-networking-kb` before
  the session.
- Stage B's `five12_ble/` dependency has **cleared** — Cintenna is merged to
  `main`. Stage B remains blocked on transport identification only.

## Plan or spec

- `docs/superpowers/plans/2026-08-04-astera-art7-bench-capture.md`

## Decisions and trade-offs

**Split into two sessions.** Session 1 is ordinary HTTP against a phone and is
all Stage A needs. Session 2 is radio transport identification and exists only to
gate Stage B. Bundling them would have made the low-risk work wait on the
high-risk work.

**Step 0 is a kill switch.** If the Remote Control server does not exist on the
shipping build, Stage A dies and the session stops there rather than continuing
to collect evidence for a dead design.

**Partial success is an accepted outcome.** If some fields confirm and others do
not, the plan maps what confirmed and leaves `VERIFIED_AGAINST_UNIT = False`. A
verification flag that means "mostly" is worse than one that means "no".

**Two blind constants and one unadopted recommendation get resolved by
measurement, not judgement:** `MAX_RESPONSE_BYTES` (1 MiB, chosen with no data),
`FETCH_TIMEOUT` (scalar `3`; the spec review recommended a `(1.0, 2.0)`
connect/read tuple and Stage A did not adopt it), and whether the deliberately
omitted failure cache is needed — which Step 6's phone-lifecycle test answers.

## Checks run

| Command | Result | Evidence level |
|---|---|---|
| none — documentation only | n/a | n/a |

## Commits

- `docs: plan the Astera ART7 bench capture session`

## Risks and skipped checks

- The plan asserts payload-shape questions but cannot answer them; every field
  mapping in Stage A remains unverified until the session runs.
- `FIVE12_ASTERA_TOOLS=1` must not be set against the show network before then.
  That rule is unchanged by this branch.
- Session 2 contends for the Windows Bluetooth radio with the Cintenna scan
  service, which is now on `main` and starts from the app factory. The Five12
  backend must be stopped, not merely reconfigured.

## Handoff / next action

Anthony: schedule the bench session, or say Stage A stands as-is and this stays
planned. Nothing else in the repo is waiting on it — Stage A is merged, gated
off, and honest about being unverified.
