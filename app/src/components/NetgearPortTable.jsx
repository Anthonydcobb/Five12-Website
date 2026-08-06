import React from 'react';
import { timeAgo } from '../utils/timeAgo';

const CELL = { padding: '3px 8px', fontSize: 12, textAlign: 'left' };
const HEAD = { ...CELL, color: 'var(--color-text-muted)', fontSize: 10, letterSpacing: 1 };

// A switch port and a DMX port share only the word "port": this has VLAN,
// profile and PoE where PortTable has universe, protocol and direction. They
// are deliberately separate components rather than one with half its columns
// blank for whichever kind it is rendering.
export default function NetgearPortTable({ device }) {
  const vd = device.vendorData || {};
  const ports = vd.netgearPorts;
  if (!ports?.length) return null;

  // Snapshots are manual and therefore stale by definition. The capture time
  // goes on the face of the panel, not in a tooltip -- an operator reading
  // this during a show needs to know at a glance whether it is ten minutes or
  // one load-in old.
  const asOf = vd.snapshotAsOf;

  return (
    <div style={{ background: 'var(--color-surface)', borderRadius: 4, padding: 8, marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 11, letterSpacing: 1 }}>
          SWITCH PORTS (SNAPSHOT)
        </div>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 10 }}>
          snapshot {asOf ? timeAgo(asOf) : 'time unknown'}
        </div>
      </div>

      {vd.netgearPortHostsAvailable === false && (
        <div style={{ color: 'var(--color-brand-hi)', fontSize: 10, marginBottom: 6 }}>
          Per-port host details were not readable from this page — VLAN, PoE and
          link state below are still accurate.
        </div>
      )}

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={HEAD}>PORT</th>
            <th style={HEAD}>PROFILE</th>
            <th style={HEAD}>VLAN</th>
            <th style={HEAD}>LINK</th>
            <th style={HEAD}>PoE</th>
            <th style={HEAD}>CONNECTED</th>
          </tr>
        </thead>
        <tbody>
          {ports.map(p => (
            <tr key={p.port} style={{ borderTop: '1px solid var(--color-border)' }}>
              <td style={CELL}>
                <span style={{
                  display: 'inline-block', width: 8, height: 8, borderRadius: 2,
                  background: p.color || 'transparent', marginRight: 6,
                }} />
                {p.port}{p.media === 'fiber' ? ' (SFP)' : ''}
              </td>
              <td style={CELL}>{p.trunk ? `Trunk (${p.trunk})` : (p.profile || '—')}</td>
              <td style={CELL}>{p.vlans?.length ? p.vlans.join(', ') : '—'}</td>
              <td style={{ ...CELL, color: p.linkUp ? 'var(--color-online)' : 'var(--color-text-muted)' }}>
                {p.linkUp ? (p.linkSpeed || 'up') : 'down'}
              </td>
              <td style={CELL}>{p.poe ? 'yes' : '—'}</td>
              <td style={CELL}>{p.host || p.ip || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
