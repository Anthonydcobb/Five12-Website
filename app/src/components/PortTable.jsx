import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { timeAgo } from '../utils/timeAgo';

const CELL = { padding: '3px 8px', fontSize: 12, textAlign: 'left' };
const HEAD = { ...CELL, color: 'var(--color-text-muted)', fontSize: 10, letterSpacing: 1 };

export default function PortTable({ device }) {
  const cached = device.vendorData?.ports;
  // `portsState.mac` records which device the `ports` payload actually
  // belongs to. DeviceDetail renders this component without a `key`, so it
  // persists across device selections — the `ports` state would otherwise
  // keep showing the outgoing device's rows for the render that happens
  // before the effect (which runs after commit) has a chance to reset it.
  // Tagging the state lets render-time derivation fall back to the new
  // device's own cached patch whenever the tag disagrees, so a stale row
  // is never committed even for one frame.
  const [portsState, setPortsState] = useState({ mac: device.macAddress, ports: cached || [] });
  // Tagged the same way as `portsState` above, and for the same reason:
  // DeviceDetail renders this component without a `key`, so on the render
  // that applies a newly-selected device's props (before the effect below
  // has committed), `stale` would otherwise still hold the OUTGOING
  // device's value. That paints the new device's fresh rows underneath the
  // previous device's "node did not answer" banner — the inverse of the
  // `portsState` bug, and the same feature-spec violation: presenting data
  // as something it is not, just in the other direction (fresh data shown
  // as stale instead of stale data shown as current).
  // `stale.value` is null to hide the banner, otherwise { asOf } — asOf may
  // itself be null when the backend has no recorded last-seen time; that
  // must still render the banner, never collapse back to the hidden state.
  const [stale, setStale] = useState({ mac: device.macAddress, value: null });

  useEffect(() => {
    // Paint the cached patch immediately on selection, then correct it. The
    // stored copy comes from the 300s sweep, so it is exactly what is wrong
    // while somebody is repatching the node in front of you.
    setPortsState({ mac: device.macAddress, ports: device.vendorData?.ports || [] });
    setStale({ mac: device.macAddress, value: null });
    if (!device.vendorData?.ports?.length) return;

    let cancelled = false;
    axios.get(`/api/network/devices/${device.macAddress}/ports`)
      .then(res => {
        if (cancelled) return;
        if (res.data.ports?.length) {
          setPortsState({ mac: device.macAddress, ports: res.data.ports });
        }
        // `live: false` means the node did not answer, full stop — the
        // banner must show regardless of whether a usable timestamp came
        // back with it. Collapsing a missing/null asOf to the same "hide
        // the banner" sentinel as live:true would present a stale patch
        // as current, which is exactly what this feature must not do.
        setStale({ mac: device.macAddress, value: res.data.live ? null : { asOf: res.data.asOf ?? null } });
      })
      // Keep showing the cached patch. A failed refresh is not a reason to
      // throw away the last thing we knew.
      .catch(() => {});
    return () => { cancelled = true; };
  }, [device.macAddress]);

  if (!cached?.length) return null;

  // If the tagged ports don't belong to the current device (the render
  // before the effect has run), fall back to this device's own cached
  // patch rather than the previous device's live/cached rows.
  const ports = portsState.mac === device.macAddress ? portsState.ports : cached;
  // Same fallback for `stale`: if the tag doesn't match the current device,
  // the previous device's stale/live status tells us nothing about this
  // one, so hide the banner rather than mislabel a freshly-selected,
  // not-yet-queried device as one that failed to answer.
  const staleValue = stale.mac === device.macAddress ? stale.value : null;

  return (
    <div style={{ background: 'var(--color-surface)', borderRadius: 4, padding: 8, marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 11, letterSpacing: 1 }}>PORTS</div>
        {staleValue !== null && (
          <div style={{ color: 'var(--color-warn)', fontSize: 10 }}>
            {/* `timeAgo(null)` returns 'never', which is wrong here: the
                node did answer at some point (that's how we have a cached
                patch) — we just don't have a recorded last-seen time for
                it. Say so honestly instead of inventing or implying one. */}
            node did not answer · {staleValue.asOf ? `as of ${timeAgo(staleValue.asOf)}` : 'time unknown'}
          </div>
        )}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={HEAD}>PORT</th>
            <th style={HEAD}>UNIVERSE</th>
            <th style={HEAD}>PROTOCOL</th>
            <th style={HEAD}>DIRECTION</th>
            <th style={HEAD}>STATUS</th>
          </tr>
        </thead>
        <tbody>
          {ports.map(p => (
            <tr key={p.port} style={{ borderTop: '1px solid var(--color-border)' }}>
              <td style={{ ...CELL, color: 'var(--color-text-muted)', fontVariantNumeric: 'tabular-nums' }}>{p.port}</td>
              <td style={{ ...CELL, color: 'var(--color-gel)', fontVariantNumeric: 'tabular-nums' }}>{p.universe}</td>
              <td style={{ ...CELL, color: 'var(--color-text)' }}>{p.protocol}</td>
              <td style={{ ...CELL, color: 'var(--color-text)' }}>{p.direction}</td>
              {/* Green ONLY for a confirmed OK. An unmapped code such as
                  'code 9' renders neutral — we can no more claim a state is
                  bad than claim it is good. */}
              <td style={{ ...CELL, color: p.status === 'OK' ? 'var(--color-online)' : 'var(--color-text-muted)' }}>
                {p.status}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
