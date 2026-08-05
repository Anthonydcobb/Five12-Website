# Astera tablet mirror — design

- **Date:** 2026-08-04
- **Author:** Claude Code, with Anthony
- **Status:** design approved, not implemented
- **Supersedes nothing.** This is not a revival of the removed ART7 adapter —
  see `docs/hardware-tests/astera-art7-stage-a.md` for why that one is gone.

## Problem

Astera gear cannot be read over the network. The 2026-08-04 bench session
established that the AsteraNext handset exposes no reachable service, and the
ART7-U has no network interface at all. The telemetry adapter built on that
assumption was removed at `ce51e20`.

What Anthony actually needs is narrower than telemetry and entirely achievable:
**the Astera controls on the PC screen, inside Five12.** Today that means picking
up a phone mid-show. The AsteraNext app itself is the control surface — it just
lives on the wrong screen.

A second requirement came out of the same conversation: **the app device should
not be his personal phone.** A dedicated Android tablet runs AsteraNext, keeps
the Bluetooth link to the ART7-U, and stays with the rig.

## Goals

1. An Astera tab in Devices showing the tablet's screen **inside the Five12 page**.
2. Tap and drag control of that screen from the PC.
3. Honest state: the operator can always tell whether what they are looking at is
   live, stale, or disconnected.
4. Nobody else on the venue network can reach the tablet through Five12.

## Non-goals

- ART7 telemetry. It does not exist over IP. Nothing here revives that.
- Smooth video or motion-accurate dragging in this version — see Staging.
- Controlling anything other than the one configured tablet.
- iOS. `scrcpy` and `adb` are Android-only; there is no supported way to control
  an iPad from Windows. This was considered and rejected.

## Approach

Three options were weighed:

| | Approach | Verdict |
|---|---|---|
| **A** | Poll `adb exec-out screencap`, render into an `<img>`, send taps via `adb shell input` | **Chosen for v1** |
| **B** | H.264 from `scrcpy-server` over WebSocket, decoded with WebCodecs | **Staged as v2** |
| **C** | `ws-scrcpy` as a Node sidecar | Rejected — adds a runtime and an uncontrolled dependency to a show machine |

**A ships inside the existing Flask + React shape with no new runtime.** Its
ceiling is **~1.9 fps**, set by on-device `screencap` latency — not by the
network. Tapping presets and reading status work well at that rate. Dragging a
colour wheel does not: you see the result, not the motion.

> **Measured 2026-08-04 — `verified on actual gear`.** On the mirror tablet
> (Samsung SM-T290, Android 11, over USB) a `screencap -p` round-trip is
> **514–644 ms, mean 529** across ten consecutive samples, giving **1.89 fps**.
> An `adb shell true` no-op costs 55 ms of that, so ~474 ms is on-device
> capture and PNG encode. The 20 KB PNG crosses an 18 MB/s USB link in about a
> millisecond, which confirms this design's central claim: the cost is the
> capture, not the transport.
>
> An earlier estimate here said 200–400 ms and 2–3 fps. That came from an S21;
> this tablet's MediaTek MT8768 is slower, so the dedicated device is
> marginally *worse* per frame than the phone it replaces. Accepted knowingly —
> it buys a device that stays mounted, cabled, and powered.
>
> Two consequences followed. A 400 ms poll is shorter than a single capture, so
> the panel now chains each capture from the completion of the last rather than
> firing on a fixed interval; and `CAPTURE_TIMEOUT` dropped from 8 s to 3 s,
> since 8 s was ~15x the real figure and froze the panel before the stale badge
> could appear.
>
> Caveat: measured with the tablet idle. `screencap` will be slower while
> AsteraNext is driving fixtures over Bluetooth, which is exactly when the
> mirror matters. Re-measure during a bench session with real gear before
> treating 750 ms as settled.

That limit is accepted deliberately. B is the fix and it is a materially larger
build — stream demuxing in Python, a WebSocket path Five12 does not have, and an
input-injection protocol. Building A first tells us whether B is needed at all,
and if it is, B replaces the transport beneath a tab that already works.

## Architecture

### The seam

Devices tabs are rendered from `/api/devices`, which is driven by
`ALL_DEVICE_IDS`. Adding `astera` back to that tuple earns the tab with **no
frontend plumbing** beyond one `PANELS` entry.

This is a real `DeviceAdapter`, not a placeholder, because it reports something
true and checkable:

```
AndroidMirrorAdapter(DeviceAdapter)
  id   = 'astera'
  name = 'Astera (tablet mirror)'

  detect()      -> configured serial present and online in `adb devices`
  get_status()  -> {available, deviceModel, androidVersion, screenW, screenH,
                    mirrorRunning, lastFrameAgeSec, alerts}
  get_history() -> connection up/down samples
```

The distinction from the deleted adapter matters and must stay legible in the
code: **that one asserted ART7 facts it could never obtain; this one asserts the
state of a link we own and can verify.** The module docstring points at the
hardware-test record so no future reader concludes the telemetry hypothesis was
revived.

`get_history()` earns its place: the wireless link dropped unprompted during the
2026-08-04 session, so connection stability is a real signal, not decoration.

### Files

| Path | Change |
|---|---|
| `backend/app/integrations/android_mirror.py` | **new** — the adapter and the adb boundary |
| `backend/app/integrations/__init__.py` | 2 lines — class map and `ALL_DEVICE_IDS` |
| `backend/app/device_routes.py` | 2 routes — `/astera/frame`, `/astera/input` (sibling to the existing Stardust-specific routes) |
| `backend/config.py` | `ENABLE_MIRROR_TOOLS`, both config classes, default off |
| `app/src/components/devices/AsteraMirrorPanel.jsx` | **new** |
| `app/src/pages/Devices.jsx` | 2 lines — import and `PANELS` entry |
| `backend/tests/test_android_mirror_*.py` | **new** |
| `app/src/components/devices/AsteraMirrorPanel.test.jsx` | **new** |

## Security model

The requirement in Anthony's words: *"I don't want others linking to my phone."*
Four layers, two of which stop other people and two of which stop this app from
becoming the weak point.

1. **The backend is loopback-only.** Verified 2026-08-04: Flask listens on
   `127.0.0.1:5000`. Nothing on the venue network can reach these endpoints.
   Coordination rule 11 already requires this and it holds today.
2. **adb authorisation.** Only devices authorised to this PC are reachable.
   **As of 2026-08-04 the transport is USB, and wireless debugging is turned
   off on the tablet** — so this layer is now physical: an attacker needs the
   cable. Wireless was measured at 0.05 MB/s against 18.18 MB/s on USB and
   abandoned; see the handoff for why. Should it ever be re-enabled, Android
   11+ wireless debugging is TLS-encrypted and authenticated, and pairing
   requires a code displayed on the tablet — not the old open `adb tcpip 5555`.
   It would also reintroduce a hazard on this rig: the `sACN` NIC owns an
   on-link `10.0.0.0/8` route, so a tablet on any `10.x` address is ARP'd out
   the lighting segment first.
3. **The device serial comes from configuration, never from request input.**
   `FIVE12_MIRROR_SERIAL`. A request cannot name a target. This is the same
   invariant `device_routes.py` states in its own docstring, and the same reason
   the deleted Astera adapter took a key into `ENDPOINTS` rather than a path.
4. **A closed command allowlist.** Exactly `screencap`, `input tap`,
   `input swipe`, `input keyevent`. No route to arbitrary `adb shell`.
   Coordinates validated as integers within the cached screen bounds.

**Gate:** `FIVE12_MIRROR_TOOLS`, default **off**, in both config classes,
mirroring `ENABLE_BLE_TOOLS`. This feature executes processes; it should not be
live on a machine that does not need it. Gate off means **no subprocess is
spawned at all**, enforced by test.

## Frame pipeline

`GET /api/devices/astera/frame` → `adb -s <serial> exec-out screencap -p` → PNG.

- **Single-flight.** A capture already running means the request returns the
  cached frame rather than spawning another. Without this, a slow tablet and a
  ~350 ms poll interval stack subprocesses until something breaks.
- **Poll only while mounted**, matching every existing panel.
- **Timeout** per capture; on expiry the last frame is retained and marked stale.

## Control mapping

`POST /api/devices/astera/input` with `{action, x, y, x2, y2, durationMs, keycode}`.

- Click → device pixels via the image's natural dimensions → `input tap`.
- Pointer down/up → `input swipe` with duration.
- Back / Home / Recents buttons → `input keyevent`.
- Screen size read once via `wm size` at connect and cached.
- Server-side rate limit, so a stuck mouse button cannot machine-gun the tablet.

## Error states

Each is a normal state with its own copy, never an exception:

| State | Panel shows |
|---|---|
| Gate off | "Tablet mirror disabled — set `FIVE12_MIRROR_TOOLS=1`" |
| No serial configured | Names `FIVE12_MIRROR_SERIAL` explicitly |
| adb binary missing | Says so, with the path it looked for |
| Tablet offline | Names the USB cable first, then unlocked screen and USB debugging, plus **Reconnect** |
| Capture timeout | Last frame retained, **stale badge showing age in seconds** |

The stale badge is load-bearing. The link dropped without warning during the
bench session, and a frozen image that looks live is the failure that has someone
pressing buttons at a tablet which stopped listening two minutes ago. A stale
frame always states its age.

## Testing

Backend, with `subprocess` poisoned the way the removed Astera gate tests
poisoned sockets — **gate off must spawn no process, and one call fails the
suite**:

- Serial is never taken from request input, under any payload
- Command allowlist holds; no path to arbitrary `adb shell`
- Coordinates: non-integer, negative and out-of-bounds all rejected
- Single-flight returns the cache instead of spawning a second capture
- Rate limit trips
- Offline device produces the offline contract, not an exception

Frontend: disabled / no-serial / offline / stale / live all render distinctly;
click math converts correctly at a non-1:1 display scale; controls absent when
disconnected.

## Staging

**v1 — this spec.** Embedded screen, tap and key control, honest states. The
panel states plainly that live video and smooth dragging are coming, so ~2 fps
reads as a known stage rather than a defect.

**v2 — approach B.** Replaces the transport underneath the same tab. Triggered
by v1 proving insufficient in real use, not by schedule.

## Open questions

1. **Tablet not yet purchased.** The design assumes a dedicated Android tablet.
   Everything works against the S21 already paired, so v1 can be built and tested
   before hardware arrives.
2. **Does AsteraNext run acceptably on a tablet?** Untested. It is a phone app;
   layout on a large screen is unknown. Worth checking before buying.
3. **PNG vs JPEG.** `screencap -p` emits PNG. Re-encoding to JPEG would need
   Pillow and is likely pointless over loopback — measure before adding it.
