import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { timeAgo } from '../utils/timeAgo';

const CELL = { padding: '3px 8px', fontSize: 12, textAlign: 'left', verticalAlign: 'top' };
const HEAD = { ...CELL, color: 'var(--color-text-muted)', fontSize: 10, letterSpacing: 1 };

// How many names to print before collapsing to a count. CARL's busiest real
// port has 6 devices behind it and its uplink has 79, so the cap has to sit
// low enough to separate "a small switch downstream" from "the uplink".
const NAME_CAP = 4;

export default function SwitchPortTable({ device, devices }) {
  const cached = device.vendorData?.switchPorts;
  // Both states are tagged with the device they describe. DeviceDetail renders
  // without a `key`, so the component persists across selections and would
  // otherwise paint the previous switch's rows — or its stale banner — over
  // the newly selected one for the render before the effect commits.
  const [portsState, setPortsState] = useState({ mac: device.macAddress, ports: cached || [] });
  const [stale, setStale] = useState({ mac: device.macAddress, value: null });

  useEffect(() => {
    setPortsState({ mac: device.macAddress, ports: device.vendorData?.switchPorts || [] });
    setStale({ mac: device.macAddress, value: null });
    if (!device.vendorData?.switchPorts?.length) return;

    let cancelled = false;
    const failed = () => setStale({
      mac: device.macAddress,
      value: { asOf: device.vendorData?.switchPortsAsOf ?? null, refreshFailed: true },
    });

    axios.get(`/api/network/devices/${device.macAddress}/switch-ports`)
      .then(res => {
        if (cancelled) return;
        // A stale backend 404s this route into index.html, and axios RESOLVES
        // with that HTML string. Treating it as a switch failure would blame
        // hardware that is working for a fault that is entirely ours.
        const wellFormed = res.data && typeof res.data === 'object' && typeof res.data.live === 'boolean';
        if (!wellFormed) return failed();
        if (res.data.switchPorts?.length) {
          setPortsState({ mac: device.macAddress, ports: res.data.switchPorts });
        }
        setStale({ mac: device.macAddress, value: res.data.live ? null : { asOf: res.data.asOf ?? null } });
      })
      .catch(() => { if (!cancelled) failed(); });
    return () => { cancelled = true; };
  }, [device.macAddress]);

  if (!cached?.length) return null;

  const ports = portsState.mac === device.macAddress ? portsState.ports : cached;
  const staleValue = stale.mac === device.macAddress ? stale.value : null;

  const byMac = {};
  for (const d of devices || []) byMac[d.macAddress.toUpperCase()] = d;

  // A MAC we cannot name renders as itself. Inventing a label would be worse
  // than a hex string an operator can look up.
  const nameFor = mac => {
    const d = byMac[mac.toUpperCase()];
    if (!d) return mac;
    return d.label ? `${d.label}${d.lastIp ? ` · ${d.lastIp}` : ''}` : mac;
  };

  return (
    <div style={{ background: 'var(--color-surface)', borderRadius: 4, padding: 8, marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 11, letterSpacing: 1 }}>SWITCH PORTS</div>
        {staleValue !== null && (
          <div style={{ color: 'var(--color-warn)', fontSize: 10 }}>
            {staleValue.refreshFailed ? 'could not refresh' : 'switch did not answer'}
            {' · '}
            {staleValue.asOf ? `as of ${timeAgo(staleValue.asOf)}` : 'time unknown'}
          </div>
        )}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={HEAD}>PORT</th>
            <th style={HEAD}>LINK</th>
            <th style={HEAD}>WHAT'S ON IT</th>
          </tr>
        </thead>
        <tbody>
          {ports.map(p => (
            <tr key={p.port} style={{ borderTop: '1px solid var(--color-border)' }}>
              <td style={{ ...CELL, color: 'var(--color-text-muted)', fontVariantNumeric: 'tabular-nums' }}>{p.name}</td>
              <td style={{ ...CELL, color: p.link === 'up' ? 'var(--color-online)' : 'var(--color-text-muted)' }}>{p.link}</td>
              <td style={{ ...CELL, color: 'var(--color-text)' }}>
                {p.deviceCount === 0 && <span style={{ color: 'var(--color-text-muted)' }}>—</span>}
                {/* Exactly one MAC is the ONLY case that proves direct
                    attachment, so it is the only case that gets to read like
                    a plain statement of what is plugged in. A stored row can
                    be half-written (deviceCount: 1 with an empty macs array)
                    since the cached path serves raw stored JSON with no
                    revalidation — say plainly that the MAC is not recorded
                    rather than crashing or rendering nothing. The port and
                    its link state are still real information. */}
                {p.deviceCount === 1 && (
                  p.macs[0]
                    ? nameFor(p.macs[0])
                    : <span style={{ color: 'var(--color-text-muted)' }}>not recorded</span>
                )}
                {p.deviceCount > 1 && (
                  <>
                    <div style={{ color: 'var(--color-warn)', fontSize: 11 }}>
                      {p.deviceCount} devices behind this port
                    </div>
                    {/* Same half-written-row exposure as above, guarded the
                        same way: a corrupt element in macs must not crash
                        the whole row. */}
                    {p.macs.slice(0, NAME_CAP).map((m, i) => (
                      <div key={m || `unrecorded-${i}`} style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>
                        {m ? nameFor(m) : 'not recorded'}
                      </div>
                    ))}
                    {p.deviceCount > NAME_CAP && (
                      <div style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>
                        +{p.deviceCount - NAME_CAP} more
                      </div>
                    )}
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
