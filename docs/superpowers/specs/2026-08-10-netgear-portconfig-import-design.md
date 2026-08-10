# NETGEAR Port Configuration page import — design

- **Date:** 2026-08-10
- **Author:** Claude Code, with Anthony
- **Status:** design approved, not implemented
- **Scope:** `backend/app/vendors/netgear_snapshot.py`,
  `POST /api/network/snapshot`, and `app/src/components/SnapshotImportPanel.jsx`
- **Supersedes:** the "parse the Port Configuration page" next step recorded in
  `2026-08-06-netgear-html-snapshot-design.md`, which assumed that page could
  become the PRIMARY per-port source. It cannot — see What the page actually is.

## Problem

Per-port `profile` and `template` currently reach `vendor_data` through
`_merge_popovers`, which is the one position-dependent mechanism in the whole
parser. Popovers live in a detached container at the end of the body, so the
only thing tying a popover to a port is document order. The merge is guarded —
it refuses unless the counts match and the ports arrived in ascending DOM order
— but a guard that refuses is still a guard that can refuse, and the guard
itself was a tautology until it was fixed on 2026-08-10.

The Port Configuration page carries the same two fields in real table rows
keyed to the port number in that same row. Reading them there removes the
ordering dependency for the fields that most need it.

## What the page actually is

> **Measured 2026-08-10 — `verified on actual gear`.** Every figure below is
> read from `backend/tests/fixtures/netgear_m4250_portconfig.html`, a real
> capture of FMB Switch 73 (M4250-10G2F-PoE+), not a synthetic fixture.

**The rows are good.** Each `.port-configuration-row` carries the port number in
`.port-cell .lan-font` and 17 `.scrollable-cells > .cell` divs of plain text.
The last two are Profile Name and Profile Template: port 3 reads `HogNet` /
`Data`, ports 1 and 2 read `Default` / `Default`. No ordering assumption is
needed — the port number and its profile are in the same row.

**But the table is virtualised.** It is a `vue-recycle-scroller`, so a saved
page contains only the rows that were rendered at capture time. The fixture
holds **10 rows for a 12-port switch**; ports 11 and 12 are absent from the
file entirely. The port graphic at the top of the same page does list all 12,
so captured-versus-expected coverage is detectable, but the missing rows cannot
be recovered from the file.

**And the page cannot identify itself.** It carries none of the Overview page's
identity fields — no `device_manageip`, `device_name`, `device_model`, no
serial. The switch's own management IP (172.16.3.73) appears only inside
attributes and scripts, never as text. A *neighbour's* IP (172.16.3.52, "FMB
Switch 52") **does** appear as visible text, in a `.port-item`, because it is
the LLDP peer on a port. The only IP a text parser can honestly read off this
page therefore belongs to a different switch.

Two consequences follow directly, and they set the whole design:

1. Portconfig **supplements**; it can never be the coverage authority.
2. Identity must be an explicit operator choice; it can never be inferred from
   the page.

Also note most `<input>` values are DOM properties rather than attributes and do
not survive the save. Only some — MTU, and the port description where one is set
— carry a real `value=`. Nothing in this design depends on an input value.

## Design

### Page detection

`netgear_snapshot.py` gains `detect_page_type(html) -> 'overview' | 'portconfig'
| None`:

- `.port-configuration-row` present → `portconfig`
- `#device_manageip` present → `overview`
- neither → `None`, which the route reports as the existing
  `422 unrecognised_page`

One paste box. The operator never classifies the page they saved.

### Request

A portconfig import posts `{html, macAddress}`. The MAC is already this
application's device key — `/api/network/devices/<mac>/ports` uses it — so no
new identifier is introduced. The panel offers only switches that already hold
an Overview snapshot.

### Storage

Results are stored under a **new top-level `netgearPortConfig` key**, a list of
`{port, profile, template}`. They are NOT merged into `netgearPorts`.

The reason is the Overview route's own write: `vendor_data = {**stored,
**parsed}`. `parsed` contains `netgearPorts`, so a later Overview re-import
replaces that list wholesale and would silently discard every
structurally-sourced profile written into it. A separate key survives an
Overview re-import, keeps the two sources distinguishable at read time, and
follows the precedent already set when `netgearPorts` was deliberately kept
apart from `ports` and `switchPorts`.

Precedence is unchanged: `netgearPortConfig` is top-level, so
`scanner._process_discovered_device`'s `{**prior, **fresh}` merge leaves it
alone exactly as it leaves `netgearPorts` alone.

### Cross-check

Before writing, the parsed profile and template are compared against the values
already on the matching `netgearPorts` entry.

Those existing values came from the popovers. A disagreement is therefore
direct evidence that the document-order association misattributed a port —
which is the one failure the popover path can still produce, and the reason
this work exists. Disagreements are reported, never fatal.

Link state and PoE are compared as a **secondary** note only, and explicitly
labelled time-sensitive: both sides read them structurally, and two captures
taken minutes apart can legitimately differ. They test nothing about the
popover association.

### Merge rules

- A port in the capture that exists in `netgearPorts` → its profile and
  template are recorded in `netgearPortConfig`.
- A port absent from the capture → untouched. This is what makes a partial
  capture safe, and it is what the virtual scroller makes routine.
- A port in the capture but absent from `netgearPorts` → reported in
  `portsInCaptureNotInBase`, not created. The Overview page remains the
  coverage authority.
- Nothing is ever deleted.

### Errors

| Condition | Status | Error |
| --- | --- | --- |
| Page is neither Overview nor portconfig | 422 | `unrecognised_page` |
| Portconfig page with no `macAddress` | 400 | `device_required` |
| `macAddress` matches no device | 404 | `unknown_device` |
| Device has no Overview snapshot yet | 409 | `no_base_snapshot` |

A successful import returns 200 with `portsUpdated`,
`portsInCaptureNotInBase`, `disagreements`, and `portConfigAsOf`. The panel
surfaces the server's `detail` verbatim, as it already does.

## Verification

Unit tests run against the real fixture, never a synthetic one:

- 10 rows parse, and the test asserts **10, not 12** — the virtualisation is
  pinned as expected behaviour so a future reader does not treat it as a bug.
- Port 3 → `HogNet` / `Data`; ports 1–2 → `Default` / `Default`.
- `detect_page_type` returns `portconfig` for this fixture and `overview` for
  `netgear_m4250_overview.html`.

Route tests cover each refusal in the table above, a merge that leaves an
uncaptured port untouched, and a seeded profile disagreement that is reported
without failing the import.

Every defect is reintroduced once to confirm the test written for it fails
without the fix. A test that cannot fail is a green light with nothing behind
it — the lesson of the popover order guard, which passed for a day while
comparing a sorted list against itself.

## Out of scope

- The Neighbor and Profiles pages. `netgear_m4250_neighbor.html` and
  `netgear_m4250_profiles.html` remain on disk and unparsed.
- Retiring `_merge_popovers`. It stays the source for host, MAC, IP, VLANs and
  the rest, and remains the only source for ports a portconfig capture misses.
- Any live REST client against the AV UI API.
