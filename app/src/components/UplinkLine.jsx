import React, { useState, useEffect } from 'react';
import axios from 'axios';

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

  // Exactly one device behind the port proves direct attachment. Anything
  // more is a path through an uplink — [MEASURED 2026-08-06] Bolero Antenna
  // #3's best candidate is a port with 73 devices behind it, and it is
  // plugged into something else entirely. Saying "on Port 12" would send an
  // operator to the wrong rack.
  const direct = value.deviceCount === 1;
  const where = `${value.switchLabel || value.switchMac} · ${value.portName}`;

  // deviceCount can arrive malformed (0, missing, non-numeric) from a stored
  // row that was never revalidated. `direct` above stays a strict `=== 1`
  // check regardless, so malformed counts always fail safe into "behind" —
  // this only decides how the "shared with N others" clause reads. A
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
      {!direct && (
        <span style={{ color: 'var(--color-text-muted)' }}>
          {' '}· shared with {others !== null ? `${others} others` : 'others'}, so this is a path, not a patch point
        </span>
      )}
    </div>
  );
}
