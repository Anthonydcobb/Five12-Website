// app/src/pages/Devices.jsx
//
// Device-aware panels layered on the Network Monitor pattern (research doc
// 2026-07-04): Starlink (gRPC telemetry), Riedel Bolero (beltpack batteries),
// LumenRadio Stardust (RDM-over-Art-Net discovery + patch reconciliation).
// All read-only. SIM toggle fabricates telemetry so the panels work without
// hardware on the network.

import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';

const POLL_MS = 3000;

// ── tiny shared pieces ───────────────────────────────────────────────────────

function Dot({ ok, warn }) {
  const c = ok == null ? 'var(--color-text-muted)' : ok ? 'var(--color-online)' : warn ? 'var(--color-warn)' : 'var(--color-brand-hi)';
  return <span style={{ color: c }}>●</span>;
}

function Tile({ label, value, unit, accent }) {
  return (
    <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg px-3 py-2 min-w-[92px]">
      <div className="text-[8px] text-text-muted uppercase tracking-widest">{label}</div>
      <div className="text-[16px] font-mono font-bold" style={{ color: accent || 'var(--color-text)' }}>
        {value ?? '—'}<span className="text-[9px] text-text-muted ml-0.5">{unit}</span>
      </div>
    </div>
  );
}

function AlertChips({ alerts }) {
  if (!alerts?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {alerts.map((a, i) => (
        <span key={i} className={'text-[9px] font-mono px-2 py-0.5 rounded-sm border ' +
          (a.level === 'crit'
            ? 'bg-brand-dim/50 border-brand text-brand-hi'
            : 'bg-amber-950/40 border-amber-700 text-warn')}>
          ⚠ {a.message}
        </span>
      ))}
    </div>
  );
}

// SVG sparkline from history samples
function Sparkline({ samples, field, color = 'var(--color-gel)', height = 34 }) {
  const vals = samples.map((s) => s[field]).filter((v) => typeof v === 'number');
  if (vals.length < 2) return <div className="text-[8px] text-text-muted font-mono h-[34px]">collecting…</div>;
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const W = 220;
  const pts = vals.map((v, i) =>
    `${(i / (vals.length - 1)) * W},${height - 3 - ((v - min) / span) * (height - 6)}`).join(' ');
  return (
    <svg width={W} height={height} className="block">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

function useDevice(id, sim) {
  const [status, setStatus] = useState(null);
  const [history, setHistory] = useState([]);
  useEffect(() => {
    let alive = true;
    const q = sim ? '?sim=1' : '';
    const poll = async () => {
      try {
        const { data } = await axios.get(`/api/devices/${id}/status${q}`);
        if (alive) setStatus(data);
      } catch { if (alive) setStatus({ available: false, reason: 'backend unreachable' }); }
    };
    const hist = async () => {
      try {
        const { data } = await axios.get(`/api/devices/${id}/history${q}`);
        if (alive) setHistory(data);
      } catch { /* keep last */ }
    };
    poll(); hist();
    const i1 = setInterval(poll, POLL_MS);
    const i2 = setInterval(hist, POLL_MS * 4);
    return () => { alive = false; clearInterval(i1); clearInterval(i2); };
  }, [id, sim]);
  return { status, history };
}

function Unavailable({ status }) {
  return (
    <div className="text-[10px] font-mono text-text-muted py-6 px-2">
      device unavailable{status?.reason ? <> — <span className="text-text-muted">{status.reason}</span></> : ''}
    </div>
  );
}

// ── Starlink panel ───────────────────────────────────────────────────────────

function fmtUptime(s) {
  if (s == null) return '—';
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d > 0 ? `${d}d ${h}h` : `${h}h ${m}m`;
}

function StarlinkPanel({ sim }) {
  const { status, history } = useDevice('starlink', sim);
  if (!status) return <div className="text-[10px] font-mono text-text-muted p-4">loading…</div>;
  if (!status.available) return <Unavailable status={status} />;
  const online = status.online;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <span className={'text-[13px] font-mono font-bold ' + (online ? 'text-online' : 'text-brand-hi')}>
          <Dot ok={online} /> {status.state}
        </span>
        <span className="text-[9px] font-mono text-text-muted">uptime {fmtUptime(status.uptimeS)}</span>
        {status.source === 'sim' && <span className="text-[8px] font-mono text-purple-400 border border-purple-800 rounded-sm px-1">SIM</span>}
      </div>
      <AlertChips alerts={status.alerts} />
      <div className="flex gap-2 flex-wrap">
        <Tile label="Down" value={status.downMbps} unit="Mbps" accent="var(--color-gel)" />
        <Tile label="Up" value={status.upMbps} unit="Mbps" accent="var(--color-online)" />
        <Tile label="Latency" value={status.latencyMs} unit="ms" />
        <Tile label="Obstruction" value={status.obstructionPct} unit="%"
          accent={status.obstructionPct > 5 ? 'var(--color-warn)' : undefined} />
        <Tile label="SNR" value={status.snr} unit="" />
        <Tile label="Outages 1h" value={status.outagesLastHour} unit=""
          accent={status.outagesLastHour > 0 ? 'var(--color-warn)' : undefined} />
      </div>
      <div className="flex gap-6 flex-wrap">
        <div>
          <div className="text-[8px] text-text-muted uppercase tracking-widest mb-0.5">Throughput (down)</div>
          <Sparkline samples={history} field="downMbps" color="var(--color-gel)" />
        </div>
        <div>
          <div className="text-[8px] text-text-muted uppercase tracking-widest mb-0.5">Obstruction %</div>
          <Sparkline samples={history} field="obstructionPct" color="var(--color-warn)" />
        </div>
      </div>
      {status.outageLog?.length > 0 && (
        <div>
          <div className="text-[8px] text-text-muted uppercase tracking-widest mb-1">Outage log</div>
          {status.outageLog.slice(0, 6).map((o, i) => (
            <div key={i} className="text-[9px] font-mono text-text-muted">
              {new Date(o.ts * 1000).toLocaleTimeString()} · {o.durationS}s · {o.cause}
            </div>
          ))}
        </div>
      )}
      <div className="text-[8px] text-text-muted font-mono">
        read-only · reverse-engineered gRPC (community protos) — fields may shift with dish firmware
      </div>
    </div>
  );
}

// ── Bolero panel ─────────────────────────────────────────────────────────────

function BatteryBar({ pct }) {
  const color = pct == null ? 'var(--color-text-muted)' : pct < 20 ? 'var(--color-brand-hi)' : pct < 40 ? 'var(--color-warn)' : 'var(--color-online)';
  return (
    <div className="flex items-center gap-1.5 w-32">
      <div className="flex-1 h-2.5 bg-[var(--color-surface)] rounded-sm overflow-hidden border border-[var(--color-border)]">
        <div style={{ width: `${pct ?? 0}%`, background: color }} className="h-full" />
      </div>
      <span className="text-[9px] font-mono w-8 text-right" style={{ color }}>{pct ?? '—'}%</span>
    </div>
  );
}

// Signal quality mirrors the Bolero GUI: 0–4 bars + a word (Excellent/Good/
// Medium/Bad/Not Connected). Riedel colors 2–4 bars "happy", 1 bar "bad",
// 0 bars "off" — reproduced here with the app's theme tokens.
function SignalBars({ quality, label }) {
  const q = quality ?? 0;
  const color = q >= 2 ? 'var(--color-online)' : q === 1 ? 'var(--color-brand-hi)' : 'var(--color-text-muted)';
  return (
    <div className="flex items-center gap-1.5" title={label ?? ''}>
      <div className="flex items-end gap-[1px] h-3" aria-label={`signal ${q} of 4`}>
        {[1, 2, 3, 4].map((n) => (
          <div
            key={n}
            style={{ height: `${n * 25}%`, background: n <= q ? color : 'var(--color-surface)' }}
            className="w-[3px] rounded-[1px]"
          />
        ))}
      </div>
      <span className="text-[9px]" style={{ color }}>{label ?? '—'}</span>
    </div>
  );
}

function BoleroPanel({ sim }) {
  const { status, history } = useDevice('bolero', sim);
  if (!status) return <div className="text-[10px] font-mono text-text-muted p-4">loading…</div>;
  if (!status.available) return <Unavailable status={status} />;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <span className="text-[13px] font-mono font-bold text-text">
          <Dot ok={status.ptpSynced} /> {status.packsOnline} packs online
        </span>
        <span className="text-[9px] font-mono text-text-muted">
          PTP {status.ptpSynced ? 'synced' : status.ptpSynced === false ? 'LOST' : '—'}
        </span>
        {status.source === 'sim' && <span className="text-[8px] font-mono text-purple-400 border border-purple-800 rounded-sm px-1">SIM</span>}
      </div>
      <AlertChips alerts={status.alerts} />

      <div>
        <div className="text-[8px] text-text-muted uppercase tracking-widest mb-1">Beltpacks — sorted by lowest battery</div>
        <table className="w-full text-[10px] font-mono">
          <thead>
            <tr className="text-text-muted text-left text-[7px] uppercase tracking-widest">
              <th className="py-0.5 font-normal">Pack</th><th className="font-normal">Battery</th>
              <th className="font-normal">Signal</th><th className="font-normal">Health</th>
              <th className="font-normal">Antenna</th><th className="font-normal">Temp</th>
              <th className="font-normal">State</th>
            </tr>
          </thead>
          <tbody>
            {status.beltpacks?.map((p) => (
              <tr key={p.id} className={'border-t border-[var(--color-surface)] ' + (p.online ? '' : 'opacity-40')}>
                <td className="py-1 text-text">{p.name}</td>
                <td><BatteryBar pct={p.batteryPct} /></td>
                <td><SignalBars quality={p.signalQuality} label={p.signalLabel} /></td>
                <td className="text-text-muted">{p.healthPct != null ? p.healthPct + '%' : '—'}</td>
                <td className="text-text-muted">{p.antenna ?? '—'}</td>
                <td className="text-text-muted">{p.tempC != null ? p.tempC + '°C' : '—'}</td>
                <td>{p.charging ? <span className="text-gel">⚡ chg</span> : p.online ? <span className="text-online">on</span> : <span className="text-text-muted">off</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex gap-2 flex-wrap">
        {status.antennas?.map((a) => (
          <div key={a.id} className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg px-3 py-2">
            <div className="text-[10px] font-mono font-bold text-text"><Dot ok={a.online} /> {a.name}</div>
            <div className={'text-[9px] font-mono ' + (a.ptpSynced ? 'text-text-muted' : 'text-brand-hi font-bold')}>
              PTP {a.ptpSynced ? 'synced' : 'LOST'}
            </div>
            <div className="text-[9px] font-mono text-text-muted">{a.packCount ?? '—'} packs</div>
          </div>
        ))}
        <div className="flex-1 min-w-[220px]">
          <div className="text-[8px] text-text-muted uppercase tracking-widest mb-0.5">Lowest battery over time</div>
          <Sparkline samples={history} field="lowestBatteryPct" color="var(--color-online)" />
        </div>
      </div>
      <div className="text-[8px] text-text-muted font-mono">
        read-only · live REST telemetry, verified against a real unit · battery % = charge, mAh in bolero.py
      </div>
    </div>
  );
}

// ── Stardust panel ───────────────────────────────────────────────────────────

function StardustPanel({ sim }) {
  const { status } = useDevice('stardust', sim);
  const [sheets, setSheets] = useState([]);
  const [sheetId, setSheetId] = useState('');
  const [recon, setRecon] = useState(null);
  const [units, setUnits] = useState([]);
  const uq = sim ? '?sim=1' : '';
  const loadUnits = useCallback(async () => {
    try { const { data } = await axios.get(`/api/devices/stardust/units${uq}`); setUnits(data); }
    catch { setUnits([]); }
  }, [uq]);
  useEffect(() => {
    loadUnits();
    const i = setInterval(loadUnits, 10000);
    return () => clearInterval(i);
  }, [loadUnits]);
  const saveLabel = useCallback(async (mac, label) => {
    try { await axios.put('/api/devices/stardust/label', { mac, label }); loadUnits(); }
    catch { /* ignore */ }
  }, [loadUnits]);

  useEffect(() => {
    axios.get('/api/shows').then(async ({ data }) => {
      const all = [];
      for (const show of data) {
        try {
          const r = await axios.get(`/api/shows/${show.id}/patch-sheets`);
          r.data.forEach((ps) => all.push({ ...ps, showName: show.name }));
        } catch { /* skip */ }
      }
      setSheets(all);
    }).catch(() => setSheets([]));
  }, []);

  const runRecon = useCallback(async () => {
    if (!sheetId) return;
    try {
      const { data } = await axios.get(`/api/devices/stardust/reconcile/${sheetId}${sim ? '?sim=1' : ''}`);
      setRecon(data);
    } catch (e) { setRecon({ available: false, reason: e.response?.data?.error || 'failed' }); }
  }, [sheetId, sim]);

  if (!status) return <div className="text-[10px] font-mono text-text-muted p-4">loading…</div>;
  if (!status.available) return <Unavailable status={status} />;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <span className="text-[13px] font-mono font-bold text-text">
          <Dot ok={status.universesUp > 0} /> {status.node}
        </span>
        <span className="text-[9px] font-mono text-text-muted">{status.address} · {status.universesUp}/8 universes · {status.fixturesDiscovered} RDM fixtures</span>
        {status.source === 'sim' && <span className="text-[8px] font-mono text-purple-400 border border-purple-800 rounded-sm px-1">SIM</span>}
      </div>
      <AlertChips alerts={status.alerts} />

      {units.length > 0 && (
        <div>
          <div className="text-[8px] text-text-muted uppercase tracking-widest mb-1">Units on network — label by MAC (sticks to the unit across IP changes)</div>
          <table className="w-full text-[10px] font-mono">
            <thead>
              <tr className="text-text-muted text-left text-[7px] uppercase tracking-widest">
                <th className="font-normal py-0.5">Label</th><th className="font-normal">MAC</th>
                <th className="font-normal">IP</th><th className="font-normal">Reported name</th>
              </tr>
            </thead>
            <tbody>
              {units.map((u) => (
                <tr key={u.mac} className="border-t border-[var(--color-surface)]">
                  <td className="py-1">
                    <input
                      defaultValue={u.label || ''}
                      placeholder="name this unit\u2026"
                      onBlur={(e) => { const v = e.target.value.trim(); if (v !== (u.label || '')) saveLabel(u.mac, v); }}
                      onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur(); }}
                      className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-sm text-[10px] font-mono text-text px-1.5 py-0.5 w-40 focus:outline-none focus:border-brand"
                    />
                  </td>
                  <td className="text-text-muted">{u.mac}</td>
                  <td className="text-text-muted">{u.ip}</td>
                  <td className="text-text-muted">{u.longName || u.shortName}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid grid-cols-4 gap-1.5">
        {status.universes?.map((u) => (
          <div key={u.universe} className={'border rounded-lg px-2 py-1.5 ' +
            (u.transmitting ? 'bg-[var(--color-surface)] border-[var(--color-border)]' : 'bg-[var(--color-bg)] border-[var(--color-surface)] opacity-50')}>
            <div className="text-[10px] font-mono font-bold text-text">
              U{u.universe} <Dot ok={u.transmitting} />
            </div>
            <div className="text-[8px] font-mono text-text-muted">
              RF {u.rfPct != null ? u.rfPct + '%' : '—'} · {u.fixtures.length} fix
            </div>
          </div>
        ))}
      </div>

      {status.outputs?.length > 0 && (
        <div>
          <div className="text-[8px] text-text-muted uppercase tracking-widest mb-1">Outputs — source, universe &amp; CRMX type</div>
          <table className="w-full text-[9px] font-mono">
            <thead>
              <tr className="text-text-muted text-left text-[7px] uppercase tracking-widest">
                <th className="font-normal py-0.5">Output</th><th className="font-normal">Name</th>
                <th className="font-normal">Source</th><th className="font-normal">Universe/Addr</th>
                <th className="font-normal">CRMX Type</th><th className="font-normal">Power</th>
              </tr>
            </thead>
            <tbody>
              {status.outputs.map((o) => (
                <tr key={o.output} className={'border-t border-[var(--color-surface)] ' + (o.enabled ? '' : 'opacity-40')}>
                  <td className="py-0.5 text-text">{o.output}</td>
                  <td className="text-text-muted">{o.name || '—'}</td>
                  <td className="text-text-muted">{o.source}</td>
                  <td className="text-text-muted">{o.universe ?? '—'}</td>
                  <td className="text-text-muted">{o.crmxType || '—'}</td>
                  <td className="text-text-muted">{o.powerMw != null ? o.powerMw + ' mW' : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {status.universes?.some((u) => u.fixtures.length > 0) && (
        <div>
          <div className="text-[8px] text-text-muted uppercase tracking-widest mb-1">RDM discovery</div>
          <table className="w-full text-[9px] font-mono">
            <thead>
              <tr className="text-text-muted text-left text-[7px] uppercase tracking-widest">
                <th className="font-normal py-0.5">Universe</th><th className="font-normal">UID</th>
                <th className="font-normal">Model</th><th className="font-normal">DMX Addr</th>
              </tr>
            </thead>
            <tbody>
              {status.universes.flatMap((u) => u.fixtures.map((f) => (
                <tr key={f.uid} className="border-t border-[var(--color-surface)]">
                  <td className="py-0.5 text-text-muted">U{u.universe}</td>
                  <td className="text-text-muted">{f.uid}</td>
                  <td className="text-text-muted">{f.model ?? '—'}</td>
                  <td className="text-text-muted">{f.dmxAddress ?? '—'}</td>
                </tr>
              )))}
            </tbody>
          </table>
        </div>
      )}

      <div className="border-t border-[var(--color-surface-2)] pt-2">
        <div className="text-[8px] text-text-muted uppercase tracking-widest mb-1">
          Patch reconciliation — RDM vs patch sheet
        </div>
        <div className="flex items-center gap-2 mb-2">
          <select value={sheetId} onChange={(e) => setSheetId(e.target.value)}
            className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-sm text-[10px] font-mono text-text-muted px-1.5 py-1">
            <option value="">select patch sheet…</option>
            {sheets.map((s) => <option key={s.id} value={s.id}>{s.showName} / {s.name}</option>)}
          </select>
          <button onClick={runRecon} disabled={!sheetId}
            className="px-2.5 py-1 text-[9px] font-bold tracking-widest bg-brand-dim/40 border border-brand text-gel rounded-sm disabled:opacity-30">
            RECONCILE
          </button>
        </div>
        {recon && !recon.available && <div className="text-[9px] font-mono text-brand-hi">{recon.reason}</div>}
        {recon?.available && recon.report.map((r) => (
          <div key={r.universe} className="mb-1.5">
            <div className="text-[10px] font-mono text-text-muted">
              U{r.universe}: patched {r.patchedCount} · discovered {r.discoveredCount}
              {r.issues.length === 0 && <span className="text-online"> ✓ clean</span>}
            </div>
            {r.issues.map((msg, i) => (
              <div key={i} className="text-[9px] font-mono text-warn pl-3">▸ {msg}</div>
            ))}
          </div>
        ))}
        {recon?.available && <div className="text-[8px] text-text-muted font-mono">{recon.note}</div>}
      </div>
      <div className="text-[8px] text-text-muted font-mono">
        read-only · RDM-over-Art-Net (standard) — no web-UI scraping · full RDM address GET is v2
      </div>
    </div>
  );
}

// ── Page shell ───────────────────────────────────────────────────────────────

const PANELS = {
  starlink: StarlinkPanel,
  bolero: BoleroPanel,
  stardust: StardustPanel,
};

export default function Devices() {
  const [sim, setSim] = useState(true);
  const [detected, setDetected] = useState([]);
  const [tab, setTab] = useState('starlink');

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const { data } = await axios.get(`/api/devices${sim ? '?sim=1' : ''}`);
        if (alive) setDetected(data);
      } catch { if (alive) setDetected([]); }
    };
    poll();
    const i = setInterval(poll, 10000);
    return () => { alive = false; clearInterval(i); };
  }, [sim]);

  const Panel = PANELS[tab];

  return (
    <div className="bg-[var(--color-bg)] text-text min-h-[calc(100vh-80px)]">
      <div className="flex items-center gap-4 px-4 py-2 bg-[var(--color-bg)] border-b border-[var(--color-surface-2)]">
        <h1 className="text-[11px] font-bold tracking-widest text-gel uppercase font-mono">Devices</h1>
        <span className="text-[9px] font-mono text-text-muted">device-aware panels · read-only telemetry</span>
        <label className="ml-auto flex items-center gap-1.5 text-[9px] font-mono text-purple-300 cursor-pointer">
          <input type="checkbox" checked={sim} onChange={(e) => setSim(e.target.checked)} className="accent-purple-500" />
          SIM MODE (no hardware needed)
        </label>
      </div>

      {/* detection cards */}
      <div className="flex gap-2 px-4 py-3 flex-wrap">
        {detected.map((d) => (
          <button key={d.id} onClick={() => setTab(d.id)}
            className={'text-left px-3 py-2 rounded-sm border min-w-[180px] ' +
              (tab === d.id ? 'border-brand bg-brand-dim/30' : 'border-[var(--color-border)] bg-[var(--color-surface)] hover:border-border')}>
            <div className="text-[11px] font-mono font-bold text-text">
              <Dot ok={d.found} /> {d.name}
            </div>
            <div className="text-[8px] font-mono text-text-muted">
              {d.found ? (d.address || 'found') : 'not detected'} · {d.detail}
            </div>
          </button>
        ))}
        {detected.length === 0 && (
          <div className="text-[10px] font-mono text-text-muted py-2">backend unreachable — start the Flask server</div>
        )}
      </div>

      <div className="px-4 pb-6 max-w-4xl">
        {Panel && <Panel sim={sim} />}
      </div>
    </div>
  );
}
