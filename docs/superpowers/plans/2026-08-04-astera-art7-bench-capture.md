# Astera ART7 / AsteraNext — bench capture plan

**Goal:** Produce the hardware evidence that turns Stage A's unverified field
mapping into a verified one, and name the ART7's radio transport so Stage B can
be estimated or killed.

**Status:** **EXECUTED 2026-08-04 — Step 0 fired, session stopped as designed.**
There is no network-reachable AsteraNext server, and the ART7-U has no network
interface at all. Steps 1–9 never ran because Step 0 gates them. Result and full
probe list: `docs/hardware-tests/astera-art7-stage-a.md`.

Session 2 (transport identification) was **not run and is not needed** for the
question it existed to answer: the ART7-U datasheet states `Bluetooth Classic:
Yes` where the ART7-WIFI states `No`, which puts Stage B on the Winsock/pywin32
branch rather than the `five12_ble/` extension. Manufacturer documentation
settled it more cheaply than an HCI capture would have.

The plan below is retained as written, minus the corrections marked **AMENDED**,
so the method is reusable if Astera ever ships a network-capable path.

**Authority:**
- `docs/agent-reviews/2026-07-29-claude-review-of-astera-integration-spec.md`
  — "Tomorrow hardware evidence needed" (items 1–11) and the Stage B evidence bar
- `docs/coordination/archive/claude--astera-stage-a.md` — the standing rule that
  `FIVE12_ASTERA_TOOLS=1` must not touch the show network until this session runs
- KB spec `five12-art7-asteranext-device-integration-spec.md` §Task 10, §10.3,
  §6.4 (`anthonydcobb/hermes-lighting-networking-kb`, branch
  `plan/five12-art7-device-integration`, `ada6841`)

**Known gap in this plan:** the KB repo is not checked out on this machine. Spec
§10.3's truth table and §6.4's sanitization list are endorsed by the review but
their text was not read while writing this. Sections 5 and 7 below are
reconstructed from the review's summary of them — **re-read §6.4 and §10.3 from
the KB before the session and reconcile**, rather than treating this file as the
authority on them.

---

## Why this session exists

Everything in `backend/app/integrations/astera.py` that touches a payload shape
is a hypothesis from static analysis of the AsteraNext 13.18 binary. No live
server has ever answered. Concretely, these are guesses:

| Guess in `_normalize()` | Normalized as |
|---|---|
| `/api/status` → `online` | `appOnline` |
| `/api/status` → `version` | `appVersion` |
| `/api/status` → `platform` | `platform` |
| `/api/status` → `bridge.name` | `bridge.name` |
| `/api/status` → `bridge.battery` | `bridge.batteryPct` |
| `/api/status` → `pin` | `radioPinAlias` (aliased, never raw) |
| `/api/targets` → `targets[].id/name/selected/brightness` | `targets[]` |

`VERIFIED_AGAINST_UNIT = False` (`backend/app/integrations/astera.py:52`) is what
makes that honest today. This session is the only thing that can flip it.

## Safety envelope — read before touching anything

1. **AMENDED — verified egress, not network isolation.** The original rule said
   "isolated network only". That was wrong: stages have no cellular service, so
   the phone is always on venue Wi-Fi, and an isolated bench network is a
   configuration that never exists in production. Capturing under it would verify
   a topology you never operate in.

   The replacement control is per-request egress verification. Before any packet,
   run `Find-NetRoute -RemoteIPAddress <PHONE_IP>` and confirm the interface is
   **not** a show NIC. This matters concretely: Management owns `172.16.0.0/16`
   while venue Wi-Fi owns `172.16.10.0/23`, so a phone addressed anywhere in
   172.16-space *outside* that /23 egresses **Management, onto the show LAN**.
   On 2026-08-04 the Windows neighbor table held a stale unresolved entry for the
   phone on Management — the overlap is real, not theoretical.

   Stop if the route resolves to Management, HOG, COMS, or sACN.
2. **Dummy fixtures only.** No show rig, no fixture that is patched into
   anything. The ART7 talks to fixtures over its own radio — an ART7 on the
   bench with the show's tubes powered nearby is not isolated.
3. **Read-only.** Only `/api/status` and `/api/targets` are ever requested.
   AsteraNext implements state changes as `GET` (`/api/launch`, `/api/set_power`,
   …). Never type one, not even to "see what happens".
4. **`FIVE12_BLE_TOOLS=0` for every HCI run.** The Cintenna scan service is now
   on `main` and starts from the app factory; it contends for the same Windows
   radio and will pollute a snoop log. Confirm the Five12 backend is stopped, not
   just that the env var is set.
5. **No fixture output changes and no configuration writes across the whole
   session.** If a fixture changes state, stop and record what preceded it.
6. **Abort conditions:** AsteraNext fails to reconnect to the ART7 after any
   step; the ART7 drops fixtures; any unexpected output. Stop, restore, write up
   what happened, do not continue to the next step.

## Session 1 — AsteraNext HTTP (Stage A verification)

Everything here is ordinary HTTP against a phone. This is the low-risk session
and it is the one Stage A actually needs.

### Setup

- `PHONE_IP` — the phone's address on the isolated network. Record it; it gets
  redacted before anything is committed.
- Capture laptop with `curl.exe`. In PowerShell, `curl` is an alias for
  `Invoke-WebRequest` — **type `curl.exe` every time** or the flags below will
  not behave.
- A scratch directory outside the repo:
  `C:\dev\five12-captures\astera-2026-08-04\`. Raw captures never land in Git;
  only sanitized ones do (§5).

### Step 0 — the kill switch. Do this first.

The whole of Stage A rests on the Remote Control server existing on the shipping
build. Answer this before spending time on anything else.

```bash
curl.exe -s -D headers-status-raw.txt -o status-raw.json -w "http=%{http_code} type=%{content_type} bytes=%{size_download} secs=%{time_total}\n" http://PHONE_IP:8080/api/status
```

- **Answers with JSON →** continue to Step 1.
- **Connection refused →** open AsteraNext settings and look for a Remote
  Control / API toggle. Photograph the settings screen either way. Enable it and
  retry.
- **No toggle and no server →** Stage A is dead as designed. Stop the session,
  record the finding, and fall back to manual inventory. Do not proceed to
  Session 2 on the assumption that Stage B rescues it — it does not; Stage B is a
  separate transport with its own gate.

### Step 1 — `/api/status`, bridge connected

Three consecutive captures, not one, so a transient field is distinguishable from
a stable one.

```bash
curl.exe -s -D headers-status-1.txt -o status-connected-1.json -w "http=%{http_code} type=%{content_type} bytes=%{size_download} secs=%{time_total}\n" http://PHONE_IP:8080/api/status
```

Repeat as `-2`, `-3` roughly ten seconds apart.

Record: every key at every level, its type, and whether it changed between the
three. Note especially whether `bridge` is nested or flat — the normalizer
assumes nested and treats a non-dict as absent.

### Step 2 — `/api/status`, ART7 disconnected

Power the ART7 down (or unpair it) and capture again as
`status-disconnected-1.json`. This case defines every state string the panel
renders, and it is the one the panel will show most often in practice.

Record: does the payload lose the `bridge` key, keep it with nulls, or keep stale
values? Does `online` refer to the app or to the bridge? The `detect()` split
between `app_reachable` and `bridge_connected` depends on this answer.

### Step 3 — `/api/targets` with at least two targets

Create two targets/sets in AsteraNext against dummy fixtures first.

```bash
curl.exe -s -D headers-targets.txt -o targets.json -w "http=%{http_code} type=%{content_type} bytes=%{size_download} secs=%{time_total}\n" http://PHONE_IP:8080/api/targets
```

Record: is the list under a `targets` key or is the top level an array? The
normalizer rejects a non-object top level outright, so an array response is a
code change, not a mapping tweak. Confirm `brightness` is a percentage and not
0–255 — `brightnessPct` claims percent.

### Step 4 — headers and redirect behaviour

B4's three controls (redirects refused, size cap, content-type required) were
written blind. Confirm them against reality using the `-D` header files already
captured, plus:

```bash
curl.exe -s -o NUL -D - http://PHONE_IP:8080/api/
curl.exe -s -o NUL -D - http://PHONE_IP:8080/
```

Record: exact `Content-Type` (if it is `text/json` or has a charset suffix, the
strict `!= 'application/json'` check rejects a real server and must be loosened);
whether `Content-Length` is present; whether any route answers 3xx.

### Step 5 — size and latency, for real numbers

From the `-w` output already collected, record the largest `size_download` seen
and the `time_total` distribution.

- `MAX_RESPONSE_BYTES` is 1 MiB, chosen blind. Set it from the measured maximum
  with generous headroom.
- `FETCH_TIMEOUT` is a scalar `3`. The review recommended a
  `timeout=(1.0, 2.0)` connect/read tuple, and the implementation did not adopt
  it. The panel polls every 3 s, so an unreachable phone blocks a worker for the
  full timeout on every poll. Decide the value from measured latency, and decide
  at the same time whether the deliberately-omitted failure cache is now needed.

### Step 6 — phone lifecycle

The phone will sleep, lock, and leave Wi-Fi far more often than a rack-mounted
antenna would. Loop for two minutes in each of three states — app foregrounded,
app backgrounded, screen off:

```bash
for i in $(seq 1 40); do curl.exe -s -o NUL -w "%{http_code} %{time_total}\n" http://PHONE_IP:8080/api/status; sleep 3; done
```

Record: does the server keep answering, answer slowly, or stop? A panel that
goes stale every time the phone locks needs different copy than one that does
not, and this decides whether last-known-good caching is required rather than
optional.

### Step 7 — addressing

- Confirm the port is 8080. If the app exposes a configurable port, record the
  default and the range.
- Determine whether the phone answers on IPv4 only. If it has an IPv6 address,
  try it bracketed:
  `curl.exe -g -s -o NUL -w "%{http_code}\n" "http://[V6_ADDR]:8080/api/status"`.
  This validates the B5 bracketing path, and confirms whether the link-local
  refusal is a real limitation or a non-issue on DHCP.

### Step 8 — PIN presence

Check whether the radio PIN appears in `/api/status` at all. The whole redaction
design assumes it does. If it does not, `radioPinAlias` is dead code and should
be removed rather than left implying a protection that has nothing to protect.
If it does, confirm the alias derivation covers its real format and width.

### Step 9 — ground truth against the hardware

Field by field, compare every captured value against the AsteraNext UI **and**
the ART7's own display. Photograph both alongside the terminal.

Battery especially: app percentage versus device display. `ALERT_RULES` fires a
`crit` at `bridge.batteryPct < 20`. If the app reports a different scale or a
coarser step than the device, that threshold is measuring something other than
what it claims.

## Session 2 — transport identification (Stage B gate only)

**Do not start this session unless Session 1 succeeded and someone actually
wants Stage B estimated.** Stage A ships without it.

The one fact required: **BLE GATT, Classic RFCOMM/SPP, or Wi-Fi.** It decides
whether Stage B extends `five12_ble/` (now merged to `main` — that dependency has
cleared) or is a different Windows stack entirely. `bleak` speaks BLE GATT only;
if the ART7 uses the `00001101-…` SPP profile, Stage B is Winsock Bluetooth
sockets / pywin32 with its own connection manager, its own tests, and a
materially larger estimate.

Evidence bar — all four, or the vote is **NO-GO**:

1. The transport is **named and photographed**, not inferred.
2. **Three clean captures** with the Cintenna scanner off.
3. AsteraNext **reconnects normally after every capture**.
4. **No fixture output or configuration change** across the whole session.

Fill in the transport truth table and reconcile it with spec §10.3:

| Observation | BLE GATT | Classic RFCOMM/SPP | Wi-Fi |
|---|---|---|---|
| Windows radio shows the ART7 as | | | |
| Service UUID / profile observed | | | |
| `bleak` can enumerate it | | | |
| Stage B implementation path | extend `five12_ble/` | new Winsock/pywin32 stack | HTTP-like, re-scope |

## Sanitization — before anything enters Git

Per spec §6.4 (re-read it; not available locally while writing this):

- Radio PIN → placeholder.
- Phone IP, MAC, hostname, and any account or device identifier → placeholder.
- Show, venue, and fixture names → generic (`AsteraBox TEST`, `Target A`).
- **Keep intact:** every key name, nesting shape, value type, and enum spelling.
  Those are the entire point of the capture; a sanitizer that renames keys
  destroys the evidence.

Raw captures stay in `C:\dev\five12-captures\` and never get committed.

## What lands in the repo afterward

| Path | Content |
|---|---|
| `backend/tests/fixtures/astera/*.json` | Sanitized captures — connected, disconnected, targets |
| `docs/hardware-tests/astera-art7-stage-a.md` | Session record, spec Task 5 evidence. Directory does not exist yet; create it |
| `backend/app/integrations/astera.py` | `_normalize()` mapping corrected against real keys; `VERIFIED_AGAINST_UNIT = True` **only if** every mapped field was confirmed; `MAX_RESPONSE_BYTES` and timeout set from measurement; `ALERT_RULES` battery threshold confirmed; `detect()` detail strings written from the real disconnected payload |
| `backend/tests/test_astera_normalize.py` | Re-pointed at the real fixtures instead of hypothesized shapes |
| `docs/coordination/reviews/` | Handoff for independent review — this changes a device integration's contract and rule 5 applies |

Evidence label for all of it: **bench-tested**, not "verified on actual gear",
unless the session ran against the real show inventory — which §Safety says it
must not.

**Partial success is the likely outcome and it is fine.** If six fields confirm
and one is absent, map the six, leave the seventh reading `None`, and leave
`VERIFIED_AGAINST_UNIT = False` with a note naming exactly what is still
unverified. A flag that means "mostly" is worse than one that means "no".

## Verification after the code changes

Run on the app interpreter, not whatever `python` is on `PATH` — the two have
different package sets on this rig:

```bash
'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q backend/tests
```

```bash
cd app && npx vitest run && npm run build
```

Confirm the gate still defaults off after the changes: with `FIVE12_ASTERA_TOOLS`
unset there must still be no DNS, no TCP probe, and no HTTP. The poisoned-socket
tests in `backend/tests/test_astera_gate.py` enforce this — they must stay green
without modification. If a capture-driven change requires editing those tests,
that is a signal the gate contract moved, and it needs saying out loud in the
handoff.
