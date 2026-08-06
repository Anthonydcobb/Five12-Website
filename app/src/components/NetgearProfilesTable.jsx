import React from 'react';
import { timeAgo } from '../utils/timeAgo';

const CELL = { padding: '3px 8px', fontSize: 12, textAlign: 'left' };
const HEAD = { ...CELL, color: 'var(--color-text-muted)', fontSize: 10, letterSpacing: 1 };

export default function NetgearProfilesTable({ device }) {
  const vd = device.vendorData || {};
  const profiles = vd.profiles;
  if (!profiles?.length) return null;

  return (
    <div style={{ background: 'var(--color-surface)', borderRadius: 4, padding: 8, marginBottom: 8 }}>
      {/* Carries its own capture time rather than relying on the ports panel's.
          The two panels are populated from independent parts of the page and
          either can render without the other, so a shared timestamp somewhere
          above them would sometimes describe data that isn't on screen. */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 11, letterSpacing: 1 }}>
          NETWORK PROFILES
        </div>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 10 }}>
          snapshot {vd.snapshotAsOf ? timeAgo(vd.snapshotAsOf) : 'time unknown'}
        </div>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={HEAD}>PROFILE</th>
            <th style={HEAD}>TEMPLATE</th>
            <th style={HEAD}>VLAN</th>
            <th style={HEAD}>PORTS</th>
          </tr>
        </thead>
        <tbody>
          {profiles.map(p => (
            <tr key={p.name} style={{ borderTop: '1px solid var(--color-border)' }}>
              <td style={CELL}>
                {/* The switch's own swatch colour, reused rather than a second
                    palette invented for the same four networks. */}
                <span style={{
                  display: 'inline-block', width: 8, height: 8, borderRadius: 2,
                  background: p.color || 'transparent', marginRight: 6,
                }} />
                {p.name}
              </td>
              <td style={CELL}>{p.template || '—'}</td>
              <td style={CELL}>{p.vlan ?? '—'}</td>
              <td style={CELL}>{p.portCount ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
