# Handoff — Astera tablet mirror: hardware facts and a poll-interval correction

- **Owner:** Claude Code
- **Reviewer:** Hermes
- **Branch:** `feat/claude/astera-mirror-impl`
- **Base / head SHA:** head `6b44418`
- **Status:** review
- **Hardware evidence:** verified on actual gear

## What changed

**Measurements taken on the real mirror tablet**, which answer the three items
the spec left unverified and contradict one of its pinned numbers — plus the
two timing corrections those measurements forced:

- `CAPTURE_TIMEOUT` 8s -> 3s in `backend/app/integrations/android_mirror.py`
- The frame poll in `AsteraMirrorPanel.jsx` re-chained to chain from capture
  completion instead of `setInterval`, and its gap raised 400 ms -> 750 ms
- Panel copy corrected from "2–3 fps" to "about 2 fps"

The dedicated device is now chosen, paired, and cabled:

| | |
|---|---|
| Model | Samsung **SM-T290** (Galaxy Tab A 8.0, 2019) |
| Android | 11 (SDK 30) |
| Serial | `R9WR90CBTMH` |
| Transport | **USB (micro-USB)** — not USB-C |
| Panel | 800x1280, density 213 |
| Apps present | `com.asteraled.asteranext`, `com.asteraled.asteraapp10` |

`FIVE12_MIRROR_SERIAL=R9WR90CBTMH`

## Three spec unknowns, now answered

### 1. `wm size` override — resolved, no parser change needed

```text
$ adb -s R9WR90CBTMH shell wm size
Physical size: 800x1280
```

**No `Override size:` line.** The concern that a second line would make the
parser return display geometry that does not match the coordinate space
`input tap` uses does not arise on this device. Task 4's blocker is cleared.

Caveat worth keeping: this is one device in one state. `Override size:` appears
after `wm size WxH` or some accessibility/display-size settings, so the parser
still ought to prefer the last line rather than assume a single one. Cheap
insurance, not a blocker.

### 2. Tablet layout — acceptable, no phone-stretch

AsteraNext renders a native three-column effects grid at 800x1280: correct
proportions, readable labels, no clipping, no letterboxing. The
dedicated-device assumption in the spec holds. Verified by on-device
`screencap` with `asteraapp.droid.MainActivity` in the foreground.

### 3. Frame rate — **the spec's 400 ms poll is shorter than a single capture**

This is the finding that needs action.

`screencap` round-trip, 10 consecutive samples over USB:

```text
$ adb -s R9WR90CBTMH exec-out screencap -p
644, 519, 514, 516, 515, 515, 515, 525, 516, 514  ms
min=514  max=644  mean=529     => 1.89 fps     (PNG, 20,431 bytes)
```

Raw capture, PNG encode skipped, 6 samples:

```text
$ adb -s R9WR90CBTMH exec-out screencap
534, 419, 456, 445, 430, 416  ms
mean=450                       => 2.22 fps     (raw, 4,096,016 bytes)
```

adb no-op baseline, to separate client spawn + transport from capture itself:

```text
$ adb -s R9WR90CBTMH shell true
79, 51, 52, 54, 54, 52, 53, 49  ms
mean=55 ms
```

So on-device capture and encode is ~474 ms of the 529 ms PNG figure. The
remaining ~55 ms is adb client spawn plus transport, and the adapter's
`_run_adb` pays that same cost per call because it also spawns a client per
invocation — the 529 ms is the number the panel will actually see.

**The spec (design doc lines 51–55) estimates 200–400 ms and a 2–3 fps
ceiling.** On this tablet the real figure is **514–644 ms and ~1.9 fps**. The
spec's *reasoning* is confirmed — the cost is on-device `screencap`, not the
link; a 20 KB PNG over an 18 MB/s USB path is ~1 ms of transfer. Only the
magnitude was optimistic, and this tablet's MediaTek MT8768 is slower at it
than the S21 the original estimate came from. Moving to the dedicated tablet
makes the frame rate slightly *worse*, not better. That is still an acceptable
trade for a device that can stay mounted and cabled, but it should be a
recorded decision rather than a surprise.

**Required change:** `POLL = 400 ms` schedules the next capture before the
current one can finish. Every cycle overruns and the queue never drains. It
should be **at least 750 ms**, and the poll should be self-pacing — schedule
the next capture from the completion of the last, not on a fixed timer.

**Suggested change:** `CAPTURE_TIMEOUT = 8` is ~15x the observed 529 ms. A
genuinely hung capture therefore freezes the panel for 8 seconds before the
stale badge appears. **3 s** is still 5x headroom and fails visibly sooner.
`ADB_TIMEOUT = 6` is fine for `devices`/`wm size`.

The raw-capture path is **not** worth taking: 15% faster but 200x the bytes,
and it needs client-side RGBA handling. Rejected.

## Why this approach

USB was chosen over wireless adb after measuring both, and the gap is not close:

| | Wireless | USB |
|---|---|---|
| 4 MB `adb push` | 82.5 s (**0.05 MB/s**) | 0.22 s (**18.18 MB/s**) |

The wireless figure is not bad Wi-Fi. Tablet radio was healthy — RSSI **-38**,
72 Mbps link, Wi-Fi 4. The collapse came from the tablet sitting on
`10.92.62.246` while the rig sat on `172.16.11.216/23`, both on one hotspot
SSID: the rig reaches the tablet directly at layer 2 but the tablet must reply
via its gateway, and that asymmetric hairpin destroys TCP throughput.

Two show-rig hazards make USB the right permanent answer rather than merely the
faster one:

1. **The `sACN` NIC owns an on-link `10.0.0.0/8` route.** Any tablet address in
   `10.x.x.x` is ARP'd out the show segment first. It is a race the good path
   can win when both ends share a segment — observed as an `Unreachable`
   neighbour on ifIndex 6 followed by a resolved one on ifIndex 18 — but it is
   a race, and losing it mid-show means a dead mirror and stray ARP on the
   lighting network. `Local Area Connection` (`10.0.0.1/8`) is a second
   claimant on the same `/8`, currently disconnected.
2. **`Find-NetRoute` and `Test-NetConnection` both misreport this.** For
   `10.92.62.246` both named `Wi-Fi` / `172.16.10.1` while the packets actually
   went to `sACN`. Diagnose with a neighbour probe, not a route query:
   `Remove-NetNeighbor` then `Get-NetNeighbor` and read the `ifIndex`.

**Wireless debugging is now off on the tablet** (`adb_wifi_enabled = 0`,
`adb mdns services` returns empty). It disabled itself when USB was connected;
the state is confirmed, not assumed. USB debugging is on
(`adb_enabled = 1`). The tablet charges over the same cable
(`AC powered: true`), so a permanently mounted device needs no second lead.

## Files and contracts affected

Changed here:

- `backend/app/integrations/android_mirror.py` — `CAPTURE_TIMEOUT` 8 -> 3
- `app/src/components/devices/AsteraMirrorPanel.jsx` — `FRAME_MS` 400 -> 750,
  `setInterval` replaced by a completion-chained `setTimeout`, copy corrected
- `app/src/components/devices/AsteraMirrorPanel.test.jsx` — new regression test

No API, schema, or contract change. `ADB_TIMEOUT` left at 6.

Still outstanding, not done here:

- `docs/superpowers/specs/2026-08-04-astera-tablet-mirror-design.md` lines 51–55
  still claim 200–400 ms / 2–3 fps
- `docs/superpowers/plans/2026-08-04-astera-tablet-mirror.md` lines 180–181
  still show `CAPTURE_TIMEOUT = 8`
- the `wm size` last-line preference noted above

Outside the repo, the operator launcher `~/OneDrive/Desktop/AsteraNext.bat` was
repointed from the S21 to `R9WR90CBTMH` over USB. That file is not tracked
here; noting it so the serial is not hunted for twice.

## Database, migration, and dependency impact

None.

## Verification actually run

All commands run against the physical tablet over USB from the Windows rig.

```text
adb devices -l
  R9WR90CBTMH  device  product:gtowifixx model:SM_T290 device:gtowifi

adb -s R9WR90CBTMH shell wm size          -> Physical size: 800x1280
adb -s R9WR90CBTMH shell wm density       -> Physical density: 213
getprop ro.build.version.release / sdk    -> 11 / 30
pm list packages | grep -i astera         -> com.asteraled.asteranext
                                             com.asteraled.asteraapp10
settings get global adb_enabled           -> 1
settings get global adb_wifi_enabled      -> 0
adb mdns services                         -> (empty)
dumpsys battery                           -> AC powered: true, status: 2

screencap -p  x10  -> mean 529 ms  (514-644)   1.89 fps
screencap     x6   -> mean 450 ms  (416-534)   2.22 fps
shell true    x8   -> mean  55 ms
adb push 4 MB      -> 0.22 s  = 18.18 MB/s  (USB)
                   -> 82.5 s  =  0.05 MB/s  (wireless, for comparison)
```

Test suites, run after the changes:

```text
# backend, on the interpreter start.ps1 launches the app with (Python 3.12)
python -m pytest -q backend/tests
  -> 631 passed, 7 skipped, 130 warnings in 14.30s

# frontend
npx vitest run
  -> Test Files 8 passed (8) | Tests 82 passed (82)
```

The new regression test was confirmed to fail before the fix, not merely to
pass after it. Against the old `setInterval`, with a capture mocked to outlive
the interval, it reported **4 concurrent captures in flight** — the stacking
this change removes.

Worth recording: the first version of that test passed against the broken
code. React mounted the frame effect *during* the fake-timer advance, after
the queue had drained, so only one capture ever ran and the concurrency
assertion was vacuous. It needed a zero-length advance to let the status
request settle and the effect register first, plus a `frameCalls > 1` sanity
assertion so it cannot silently go vacuous again.

## Operator acceptance test

1. Cable the tablet to the rig. Confirm `adb devices -l` lists `R9WR90CBTMH`
   as `device` — not `unauthorized`, not absent.
2. If absent, suspect the cable before anything else. Charge-only micro-USB
   cables power the tablet and are invisible to adb.
3. Launch AsteraNext on the tablet; confirm the effects grid fills the screen.
4. With the panel built, confirm frames advance at roughly one every 0.75 s and
   that the stale badge appears within ~3 s of unplugging the cable.

## Known risks / skipped checks

- **One device, one session.** Every number here is from a single SM-T290 on
  one afternoon. Thermal state and battery level (35%, charging) were not
  controlled for.
- **Timings include adb client spawn.** That is deliberate — the adapter pays
  the same cost — but it means these are end-to-end panel-visible figures, not
  clean device benchmarks.
- **`screencap` latency was not measured with the tablet under load.** It will
  be worse while AsteraNext is talking to fixtures over Bluetooth, which is
  exactly when the mirror matters. Worth a second pass during a bench session
  with real gear connected.
- **Duplicate transports are still a live trap.** With wireless debugging on,
  one physical tablet appeared **twice** in `adb devices` — once by IP, once by
  mDNS name — and scrcpy refused to choose. Dropping the phone did not remove
  this; only the `-s` pin does. Any code path that shells `adb` without `-s`
  will break the moment wireless debugging is re-enabled.
- The `wm size` single-line result is verified only in the device's current
  display configuration.

## Reviewer findings

### Critical

### Warnings

### Suggestions

### Looks good

## Next action

Items 1 and 2 are **done** in this branch; 3 and 4 are not.

1. ~~Raise the poll to >=750 ms and make it self-pacing.~~ Done.
2. ~~Lower `CAPTURE_TIMEOUT` to 3 s.~~ Done.
3. Amend the design doc's 200–400 ms / 2–3 fps claim to the measured
   514–644 ms / ~1.9 fps, labelled `verified on actual gear`. **Open.**
4. Prefer the last line of `wm size` output. **Open.**

Hermes to review 1 and 2 independently per rule 5 — particularly whether 750 ms
is the right gap, since it was chosen from idle-tablet measurements and the
tablet will be busier in use.

Task 4 is unblocked and can proceed in parallel — its blocker was the
`Override size:` question, which is answered.
