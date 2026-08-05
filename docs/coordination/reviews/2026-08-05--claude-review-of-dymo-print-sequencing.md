# Review — DYMO print sequencing (PR #11)

- **Reviewer:** Claude
- **Branch reviewed:** `fix/claude/dymo-print-sequencing` @ `9ad16e9`
- **Base:** `8291f77` (`origin/main`)
- **Date:** 2026-08-05

> **This is a self-review and should be weighted accordingly.** Rule 5 asks for
> separate implementation and review; I wrote this branch. Hermes was the named
> reviewer and was unavailable. I have tried to compensate by attacking the
> work rather than confirming it, but a second reader who did not write the
> code is still owed here — particularly on the two Critical items, which are
> judgement calls about honesty of reporting rather than mechanical defects.

Re-verified on the rebased tree before reviewing: backend `661 passed, 7
skipped`; frontend `11 files, 133 passed`; `npm run build` clean.

## Critical

### C1 — A stuck queue is counted as a successfully printed label

`awaitQueueDrain` returns `{ fault: null }` when `JOB_CEILING_MS` (15 s)
expires, and `printMerge` treats a null fault as success: `printed += 1`, then
straight on to the next record. A printer whose queue never drains therefore
produces a run that finishes reporting **every label printed**.

The behaviour is deliberate and pinned — *"a queue stuck non-empty hits the 15s
ceiling and the run continues instead of hanging"*. Not hanging is right. But
the alternative to hanging is not "silently claim success". This branch's own
stated goal is honest run outcomes, and `docs/coordination/README.md` rule 14
says never report an unrun check as passing. A ceiling expiry is precisely an
unrun check: the code knows it never observed the queue drain.

The same path swallows backend failure. `catch { q = null; }` means a backend
that is down for the full 15 s produces the identical "all printed" result with
nothing verified at all.

**Suggested fix:** give the ceiling and the never-verified cases their own
outcome — a third state alongside `stopped` and clean completion, surfaced as
something like *"12 of 40 printed; 3 could not be confirmed"*. Counting them is
defensible; reporting them as confirmed is not.

### C2 — The APPEAR give-up can silently restore the exact defect this branch fixes

Phase 1 waits up to `APPEAR_GRACE_MS` (2 s) for `jobCount > 0`, then breaks
"regardless — may have already drained". Phase 2 then polls and returns
immediately on `jobCount === 0`.

Those two states are indistinguishable to this code. If the job has **not yet
reached the spooler**, DRAIN sees zero jobs, declares the label done, and
`printMerge` submits the next label immediately — back-to-back submission,
which is the buzz-and-misregistration bug the whole branch exists to prevent.
It would fail exactly when the machine is loaded, and it would report success.

Measured on this rig, the grace window is tighter than it looks: the backend
probe takes **791 ms** (below), so a poll cycle is ~1.19 s and the 2 s window
allows roughly three attempts. Fine when the spooler is prompt; the failure
mode is silent when it is not.

**No test covers this path.** The suite pins the stuck-queue ceiling and the
transient-fetch-failure case, but nothing exercises "job never appears".

**Suggested fix:** track whether a job was ever observed for this label. If
APPEAR expired without ever seeing `jobCount > 0`, that is not a drain — treat
it as unconfirmed (see C1) rather than as a completed label.

## Warnings

### W1 — The injection invariant is asserted in a comment and proven by nothing

`print_queue_routes.py` carries a `SECURITY:` block stating the printer name is
never interpolated into the PowerShell command line. The design is right: the
command is a fixed literal and the client string is only ever compared in
Python.

But all seven backend tests patch `subprocess.run` and inspect only the
response. **Not one asserts what was passed to it.** A later "optimisation"
that appends `-PrinterName $name` to the script would keep the whole suite
green while turning a fixed literal into a command-injection vector.

This repo already knows the pattern — `android_mirror` poisons `subprocess` so
that a single call fails the suite, and this folder's own README says an
untested fail-closed claim is just a claim. The same standard applies here.

**Suggested fix:** assert that the argv passed to `subprocess.run` is unchanged
by a hostile printer name (`'; Remove-Item C:\ -Recurse #`), and that the name
appears nowhere in it.

### W2 — The probe costs 791 ms and is polled as if it cost nothing

`QUEUE_POLL_MS = 400` reads like a 400 ms cadence. Measured on this rig with
five printers installed, the spooler probe takes **791 ms mean** (759–844 over
five runs), so the real cadence is ~1.19 s. The loop is correctly self-pacing —
it awaits the fetch *before* sleeping, so polls cannot stack — but the constant
misdescribes what happens, and the 15 s ceiling is ~12 polls rather than the
~37 the name implies.

The probe also enumerates **every** printer and every printer's jobs on each
call, then discards all but one. At ~1.8 s per label that is roughly two
PowerShell spawns per label — ~200 process spawns for a 100-label run — and it
gets slower as printers are added to the rig.

**Suggested fix:** rename the constant to reflect that it is a gap between
polls rather than a period, and consider passing the printer name to PowerShell
as a bound parameter (via `-File` with an argument, or stdin) so only the one
printer's jobs are fetched. A parameter is not interpolation, so this keeps W1's
invariant intact — but it must be landed together with W1's test.

## Suggestions

- **S1** — Four distinct failures (timeout, non-zero exit, unparseable JSON,
  PowerShell missing) all return the same bare `spooler query failed`. The
  mirror adapter next door names the actual path it tried and the variable to
  set. An operator hitting this gets nothing actionable.
- **S2** — A missing `?printer=` yields `404 unknown printer`, which reads as
  "that printer does not exist" rather than "you forgot the parameter". `400`
  would be truthful.
- **S3** — `faultFrom` will trip on a stale `PaperOut` still latched on the
  printer from a previous run, ending a fresh run before its first label. Worth
  confirming the spooler clears that promptly, since the failure is confusing.

## Looks good

- **The drain loop is self-pacing.** It awaits each probe before sleeping, so
  slow probes delay the next rather than stacking. This is the bug the Astera
  mirror panel had today, done correctly here.
- **`faultFrom` checks both the printer and the individual job, paper before
  error.** The comment explains precisely why — `PrintJobStatus` is a flags enum
  whose `ToString()` yields `"Printing, PaperOut"`, so a job can carry a paper
  fault while the printer still reads Normal. Checking only the printer let a
  run feed an empty printer and report success. That is a real bug, found and
  fixed.
- **No `labelSetXml`, and embedded `DataRows` are cleared** so a template cannot
  drive the label count. Both pinned by tests.
- **Abort semantics are honest.** Stop halts between labels, the in-flight label
  is counted because it genuinely completes, and the UI says so rather than
  implying a clean cancel.
- **The design doc was amended when the premise broke** — `GetJobStatus` does
  not exist, and the branch says so in a commit rather than quietly working
  around it.

## Recommendation

**Changes requested.** C1 and C2 are the same underlying gap — the run cannot
distinguish "confirmed printed" from "never confirmed", and reports both as
success. On a show rig producing fixture labels, a run that claims forty labels
and delivered thirty-seven is worse than one that admits it does not know.

W1 should land with any change to the backend module.

Nothing here suggests the branch is wrong about the hardware. The core finding —
that `PrintLabel` returns on accept, not on feed — is well evidenced and the
sequencing built on it is sound.
