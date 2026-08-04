# Astera ART7 Stage A — hardware test record

- **Date:** 2026-08-04
- **Operator:** Anthony (hardware), Claude Code (probes and analysis)
- **Evidence level:** **bench-tested**
- **Result:** **Stage A's design premise is falsified.** There is no network-reachable
  AsteraNext server. Five12 cannot obtain Astera telemetry over IP with this
  hardware and this app.
- **Plan executed:** `docs/superpowers/plans/2026-08-04-astera-art7-bench-capture.md`,
  Session 1. Step 0 — the kill switch — fired.

## Hardware and software under test

| Item | Value |
|---|---|
| Bridge | **ART7-U** (AsteraBox), confirmed by operator against the unit |
| App | **Astera Next**, Android handset, app open and foregrounded |
| App↔bridge state | Connected — the operator confirmed the app was linked to the ART7-U throughout |
| Handset address | private /23 on the venue Wi-Fi (redacted) |
| Five12 host | same /23, Wi-Fi interface |

The ART7-U datasheet is decisive on one point that shaped the rest of this
session: **the ART7-U has no network interface of any kind.** Its radios are UHF,
CRMX and Bluetooth. Only the ART7-WIFI variant carries a WiFi module. The bridge
therefore can never hold an IP address, and the handset running Astera Next is the
only network-reachable element in the entire Astera system.

## Network context, and a correction to the plan

The plan's first safety rule required an isolated network. **That rule was wrong
and has been amended.** Stages have no cellular service, so the Astera Next
handset is always on venue Wi-Fi — an isolated bench network is a configuration
that never exists in production, and verifying against one would produce
confidence that does not transfer.

This session ran on the venue Wi-Fi, which **is** the production topology. The
substituted control was per-request egress verification rather than network
isolation:

- `Find-NetRoute` confirmed the handset matched `172.16.10.0/23` on the **Wi-Fi**
  interface, on-link, before any packet was sent.
- Verified real, not assumed: the Windows neighbor table carried a **stale,
  unresolved entry for the same address on the Management interface**
  (`00-00-00-00-00-00`, Unreachable). Windows did attempt resolution on the show
  NIC. The `172.16.0.0/16` Management route genuinely does overlap the Wi-Fi /23,
  and Wi-Fi won only because it is the more specific prefix and the handset
  happened to land inside it. A handset addressed anywhere else in `172.16.x.x`
  would have egressed **Management, onto the show LAN.** This is a live hazard for
  any future session and belongs in the runbook, not in a footnote.

Radio-side safety held: no fixture output changed, no configuration was written,
and the app remained connected to the bridge for the duration.

## Probes and results

All probes targeted the handset only.

| # | Probe | Result |
|---|---|---|
| 1 | ICMP to handset | **Reachable**, 99–342 ms — no AP client isolation |
| 2 | `GET /api/status` on port 8080 | **No connection** (`curl` exit 7, no RST) |
| 3 | 23 likely service ports, app state unknown | **None listening** |
| 4 | Same 23 ports, app open and foregrounded | **None listening** |
| 5 | **Full TCP scan, ports 1–65535**, app open and connected | **Two listeners: two ephemeral-range ports** |
| 6 | Those two ports, re-probed 3× each | Genuinely open and stable — not scan artifacts |
| 7 | HTTP `GET /` and `GET /api/status` against both | **No response at all** — connection accepted, nothing returned |
| 8 | Unsolicited banner read, 2.5 s, both ports | **Silent** |
| 9 | TLS ClientHello via `openssl s_client`, both ports | **Not TLS** — ClientHello accepted, connection closed with no reply |
| 10 | mDNS/DNS-SD enumeration (`_services._dns-sd._udp.local`, `_http._tcp.local`) | Handset advertises **nothing**. ~100 other devices on the same LAN answered, which proves the probe worked |
| 11 | Art-Net `ArtPoll` unicast to the handset | **No ArtPollReply** |

Note on the two open ports: both sit in the **ephemeral** range. Even in the
counterfactual where one of them is Astera Next, a design keyed to
`FIVE12_ASTERA_HOST` plus a fixed port `8080` could never have reached it, because
an ephemeral port is reassigned on each app launch.

## What this falsifies

Stage A was built on a static-analysis hypothesis: that Astera Next runs a
"RemoteControl" HTTP server on port 8080 answering `/api/status` and
`/api/targets`. The `/api/*` strings found inside the app binary were real. They
are **not reachable over the network** on the shipping build — they are internal
to the app, or belong to a component that is not shipped.

`backend/app/integrations/astera.py` carries `VERIFIED_AGAINST_UNIT = False` and
emits `protocolVerified: false` on every read. That flag was correct, and it stays
`False` — not because verification is pending, but because **there is nothing to
verify against.** The honesty labels did their job: this result costs nothing to
absorb, because nothing was ever built on top of the assumption.

## What this does *not* establish

Stated plainly so the record is not read as stronger than it is:

- **UDP was not swept.** Only two targeted UDP probes ran (mDNS, Art-Net). A
  proprietary UDP protocol between app and some peer would not have been seen.
  Blind UDP sweeping was judged worthless here — silence is the expected response
  on every closed *and* open UDP port.
- **The two open TCP ports remain unidentified.** They speak neither HTTP nor TLS
  and emit no banner. They could be Astera Next using a private binary protocol,
  or unrelated Android services.
- **IPv6 was not tested.**
- The app was exercised in one state only: open, foregrounded, connected. Steps
  1–9 of the plan (payload capture, header capture, phone-lifecycle behaviour,
  field-by-field ground truth) never ran, because Step 0 gates them and Step 0
  failed.

## Consequences

**Stage A cannot work as designed.** There is no IP path to Astera data — not to
the bridge, which has no network interface, and not through the app, which exposes
no reachable service.

**Stage B moves to the expensive branch.** The ART7-U datasheet lists
`Bluetooth Classic: Yes` (BT 4.0/4.1), while the ART7-WIFI variant lists
`Bluetooth Classic: No` (BT 5.0 LE). The specification sheet draws that
distinction deliberately, which makes Classic RFCOMM the likely app↔bridge
transport on the ART7-U. `bleak` speaks BLE GATT only and **cannot** do Classic
RFCOMM/SPP. If Stage B is ever attempted on this hardware it is a separate Windows
stack — Winsock Bluetooth sockets or pywin32 — with its own connection manager and
its own tests, not an extension of `five12_ble/`.

This is inference from an official datasheet, not from a capture. It is the
strongest evidence available short of an HCI trace, and it is the manufacturer's
own document, which satisfies coordination rule 9 in a way a packet capture would
not have improved on.

## Recommendation

The merged Astera adapter is gated off by default and performs no network activity
with `FIVE12_ASTERA_TOOLS` unset, so **nothing is broken and nothing is urgent.**

What should not persist is a Devices-tab panel implying a feature that cannot
work. The disabled card currently reads as "switched off", which now misleads —
the honest reading is "not achievable on this hardware". Recommended follow-up, as
a separate reviewed change rather than folded into this record:

1. Either remove the Astera adapter, panel and tests, or retain them behind the
   gate with the panel copy rewritten to state that no network path exists.
2. Keep this document either way. Its value is preventing a second team from
   spending a second session rediscovering the same result.

Anthony's call. Both options are defensible; silently leaving the current copy in
place is not.
