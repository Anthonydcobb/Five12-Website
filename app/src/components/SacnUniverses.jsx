// Live sACN (E1.31) universes — what is on the wire and who is sourcing it.
// Backed by GET /api/network/sacn (backend/app/sacn_listener.py).
//
// Kept out of NetworkMonitor.jsx deliberately: that page is already 622 lines.
// See docs/superpowers/specs/2026-07-20-sacn-listener-design.md §8.
import React, { useState, useEffect } from 'react';
import axios from 'axios';

const POLL_MS = 2000;

// Multiple sources on one universe at the SAME priority is the conflict a tech
// is actually hunting for — receiver behaviour is then arbitrary. Distinct
// priorities are a legitimate backup/tracking setup, so those are not flagged.
function conflictLevel(universe) {
  const active = universe.sources.filter(s => s.active);
  if (active.length < 2) return null;
  const top = Math.max(...active.map(s => s.priority));
  return active.filter(s => s.priority === top).length > 1 ? 'contending' : 'backup';
}

export default function SacnUniverses() {
  const [state, setState] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await axios.get('/api/network/sacn');
        if (!cancelled) { setState(res.data); setFailed(false); }
      } catch {
        if (!cancelled) setFailed(true);
      }
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  const muted = { color: 'var(--color-text-muted)', fontSize: 11 };
  const header = (
    <div style={{ ...muted, letterSpacing: 1, marginBottom: 6 }}>
      LIVE sACN UNIVERSES
    </div>
  );

  if (failed) {
    return <div>{header}<div style={muted}>API unreachable.</div></div>;
  }
  if (!state) {
    return <div>{header}<div style={muted}>Loading…</div></div>;
  }

  // Two distinct empty states: the listener never started (say why) vs. the
  // listener is up and the wire is quiet. Conflating them would let a broken
  // socket read as "no lighting traffic", which is the wrong conclusion at 6pm
  // on a show day.
  if (!state.listening) {
    return (
      <div>
        {header}
        <div style={{ ...muted, color: 'var(--color-offline, #d66)' }}>
          Listener unavailable: {state.error || 'unknown reason'}
        </div>
      </div>
    );
  }
  if (state.universes.length === 0) {
    return (
      <div>
        {header}
        <div style={muted}>
          Listening on {state.interfaces.length} interface
          {state.interfaces.length === 1 ? '' : 's'} — nothing on the wire.
        </div>
      </div>
    );
  }

  const cell = { padding: '3px 8px', textAlign: 'left', fontSize: 12 };
  const th = { ...cell, ...muted, fontWeight: 'normal', letterSpacing: 0.5 };

  return (
    <div>
      {header}
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={th}>UNIV</th>
            <th style={th}>SOURCE</th>
            <th style={th}>IP</th>
            <th style={{ ...th, textAlign: 'right' }}>PRIO</th>
            <th style={{ ...th, textAlign: 'right' }}>FPS</th>
            <th style={th} />
          </tr>
        </thead>
        <tbody>
          {state.universes.map(u => {
            const conflict = conflictLevel(u);
            return u.sources.map((s, i) => (
              <tr key={`${u.universe}-${s.cid}`}
                  style={{ borderTop: i === 0 ? '1px solid var(--color-surface)' : 'none' }}>
                {/* Stacked rows under one universe number — that adjacency is
                    what makes a double-source visible at a glance. */}
                <td style={{ ...cell, color: 'var(--color-gel)' }}>
                  {i === 0 ? u.universe : ''}
                  {i === 0 && conflict === 'contending' && (
                    <span title="Two sources at equal priority — receiver behaviour is arbitrary"
                          style={{ color: 'var(--color-offline, #d66)', marginLeft: 4 }}>⚠</span>
                  )}
                </td>
                <td style={{ ...cell, opacity: s.active ? 1 : 0.45 }}>{s.name}</td>
                <td style={{ ...cell, ...muted, opacity: s.active ? 1 : 0.45 }}>{s.ip}</td>
                <td style={{ ...cell, ...muted, textAlign: 'right' }}>{s.priority}</td>
                <td style={{ ...cell, ...muted, textAlign: 'right' }}>
                  {s.active ? s.fps : '—'}
                </td>
                <td style={cell}>
                  <span title={s.active ? 'Live' : `Last seen ${s.lastSeen}`}
                        style={{
                          color: s.active ? 'var(--color-online, #6c6)' : 'var(--color-text-muted)',
                        }}>●</span>
                </td>
              </tr>
            ));
          })}
        </tbody>
      </table>
    </div>
  );
}
