import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { timeAgo } from '../utils/timeAgo';

const CELL = { padding: '3px 8px', fontSize: 12, textAlign: 'left' };
const HEAD = { ...CELL, color: 'var(--color-text-muted)', fontSize: 10, letterSpacing: 1 };

export default function PortTable({ device }) {
  const cached = device.vendorData?.ports;
  const [ports, setPorts] = useState(cached || []);
  const [stale, setStale] = useState(null);

  useEffect(() => {
    // Paint the cached patch immediately on selection, then correct it. The
    // stored copy comes from the 300s sweep, so it is exactly what is wrong
    // while somebody is repatching the node in front of you.
    setPorts(device.vendorData?.ports || []);
    setStale(null);
    if (!device.vendorData?.ports?.length) return;

    let cancelled = false;
    axios.get(`/api/network/devices/${device.macAddress}/ports`)
      .then(res => {
        if (cancelled) return;
        if (res.data.ports?.length) setPorts(res.data.ports);
        setStale(res.data.live ? null : res.data.asOf || null);
      })
      // Keep showing the cached patch. A failed refresh is not a reason to
      // throw away the last thing we knew.
      .catch(() => {});
    return () => { cancelled = true; };
  }, [device.macAddress]);

  if (!cached?.length) return null;

  return (
    <div style={{ background: 'var(--color-surface)', borderRadius: 4, padding: 8, marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 11, letterSpacing: 1 }}>PORTS</div>
        {stale !== null && (
          <div style={{ color: 'var(--color-warn)', fontSize: 10 }}>
            node did not answer · as of {timeAgo(stale)}
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
