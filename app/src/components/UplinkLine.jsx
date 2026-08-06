import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { timeAgo, parseUtc } from '../utils/timeAgo';

// Two real discovery cycles, not two DISCOVERY_INTERVALs. backend/app/scanner.py
// sleeps DISCOVERY_INTERVAL (300s, scanner.py:43) AFTER each sweep finishes
// (scanner.py's `_discovery_loop`: run_scan_now() then time.sleep), so the
// true period between sweeps is 300s + sweep_duration, not a flat 300s. And
// start_scanner's own docstring (scanner.py:718) puts a full discovery pass
// at ~165s measured on the rig — before this branch added four SNMP walks
// per Luminex switch to every sweep, which lengthens sweep_duration further.
// So one switch's consecutive stamps can already land up to
// DISCOVERY_INTERVAL + 2*sweep_duration (~630s) apart on a perfectly healthy
// rig — over the old 600_000ms bound. Use 2x the real (inflated) cycle,
// 2*(300+165)=930s, rounded up for headroom against this branch's added
// walks, rather than pin an exact number to an unmeasured sweep duration.
// That matters here more than anywhere else in the app because the stored
// maps have NO expiry: read_switch_ports returns {} on failure by design and
// the scanner merges shallowly, so a dark switch keeps its last map in the
// database forever, across restarts. Too LOW a bound is its own failure mode:
// it declares healthy, answering switches silent on every ordinary sweep,
// training an operator to ignore the one time it is true. Without an upper
// bound at all the line would keep saying "on Luminex (CARL) · Port 5" long
// after the device was repatched to another rack.
const STALE_MS = 1_200_000;

export default function UplinkLine({ device }) {
  // Tagged with the device it describes: this component persists across
  // selections, and showing the previous device's switch port under the new
  // device's name would be a confident, wrong answer.
  const [hit, setHit] = useState({ mac: device.macAddress, value: null });

  useEffect(() => {
    setHit({ mac: device.macAddress, value: null });
    let cancelled = false;
    axios.get(`/api/network/devices/${device.macAddress}/uplink`)
      .then(res => {
        if (cancelled) return;
        if (res.data && typeof res.data === 'object' && typeof res.data.found === 'boolean') {
          setHit({ mac: device.macAddress, value: res.data });
        }
      })
      // Silent: this is a supplementary line, and a failed lookup is not
      // evidence about where the device is. Saying nothing beats guessing.
      .catch(() => {});
    return () => { cancelled = true; };
  }, [device.macAddress]);

  const value = hit.mac === device.macAddress ? hit.value : null;
  if (!value) return null;

  if (!value.found) {
    return (
      <div style={{ color: 'var(--color-text-muted)', fontSize: 11, marginBottom: 8 }}>
        No switch has seen this device
      </div>
    );
  }

  // A forwarding database records where a MAC was LAST SEEN, not what is
  // plugged in where. Two things have to hold before this line may state
  // attachment in the present tense:
  //
  // 1. Exactly one device behind the port. Anything more is a path through an
  //    uplink — [MEASURED 2026-08-06] Bolero Antenna #3's best candidate is a
  //    port with 73 devices behind it, and it is plugged into something else
  //    entirely. Saying "on Port 12" would send an operator to the wrong rack.
  // 2. The map it came from is recent. The table also ages: FDB entries expire
  //    when a device goes quiet, so absence is not proof of unplugging, and a
  //    stored map that stopped being refreshed is not proof of anything at
  //    all. A missing asOf — which every row swept before this shipped will
  //    have — is NOT freshness. No evidence of age is not evidence of youth,
  //    so it falls to the hedged branch.
  const ageMs = value.asOf ? Date.now() - parseUtc(value.asOf) : null;
  // A stamp AHEAD of the browser clock makes ageMs negative. Without the
  // `>= 0` guard, Number.isFinite(-14_400_000) is true and
  // -14_400_000 < STALE_MS is true, so `fresh` would stay true forever — the
  // identical "elapsed time went negative, so nothing ever reads as old"
  // arithmetic failure documented at the top of utils/timeAgo.js, one layer
  // up. A stamp from the future is no more evidence of youth than a missing
  // one, so it is handled separately below (`future`) and always hedges.
  const future = ageMs !== null && Number.isFinite(ageMs) && ageMs < 0;
  const fresh = ageMs !== null && Number.isFinite(ageMs) && ageMs >= 0 && ageMs < STALE_MS;
  const direct = value.deviceCount === 1 && fresh;
  const where = `${value.switchLabel || value.switchMac} · ${value.portName}`;

  // Staleness has to be said in WORDS, not signalled only by the switch from
  // "on" to "behind" — the sibling switch-side pane renders "switch did not
  // answer · as of 3h ago", and an operator reading these two panes should
  // never get a confident answer from one and a hedged one from the other with
  // no explanation of the difference.
  const ageNote = !value.asOf
    ? 'age unknown, so this may already have changed'
    : future
      // Never format a negative elapsed time through timeAgo() here — that
      // renders as e.g. "as of -14400s ago", which reads as a display glitch
      // rather than the warning it is supposed to be. State the actual
      // problem in words instead.
      ? 'reported timestamp is in the future, so its age cannot be trusted; this may already have changed'
      : fresh
        ? `as of ${timeAgo(value.asOf)}`
        : `last confirmed ${timeAgo(value.asOf)}; the switch has not reported since, so this may already have changed`;

  // deviceCount can arrive malformed (0, missing, non-numeric) from a stored
  // row that was never revalidated. `direct` above keeps a strict `=== 1`
  // check as one of its two conditions, so malformed counts always fail safe
  // into "behind" — this only decides how the "shared with N others" clause
  // reads. A
  // deviceCount of 0 here is itself a contradiction (this device is
  // apparently behind the port, so the count can't be zero), same as a
  // missing or non-numeric count: treat all of them as unusable and say
  // nothing about the number rather than state a nonsense (negative/NaN/0)
  // one.
  const others = Number.isFinite(value.deviceCount) && value.deviceCount >= 1
    ? value.deviceCount - 1
    : null;

  return (
    <div style={{ color: 'var(--color-gel)', fontSize: 11, marginBottom: 8 }}>
      {direct ? `on ${where}` : `behind ${where}`}
      {/* Gated on the COUNT, not on `direct`: a lone device behind a stale map
          is hedged by the age note below, and "shared with 0 others" would be
          a false claim about the port. */}
      {value.deviceCount !== 1 && (
        <span style={{ color: 'var(--color-text-muted)' }}>
          {' '}· shared with {others !== null ? `${others} others` : 'others'}, so this is a path, not a patch point
        </span>
      )}
      <span style={{ color: fresh ? 'var(--color-text-muted)' : 'var(--color-warn)' }}>
        {' · '}{ageNote}
      </span>
    </div>
  );
}
