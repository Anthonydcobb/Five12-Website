// app/src/pages/Console.jsx
//
// ⚠️ PARKED 2026-07-22 — not wired into the app. The /console route and the
// Header nav link were removed because this prototype isn't finished yet. This
// file and its engine (src/engine/*, src/components/LightSimulator.jsx) are
// deliberately kept so the work can resume later. To bring it back: re-add
// `import Console from './pages/Console'` + the <Route path="/console"> in
// App.jsx, and the nav <li> in components/Header.jsx. Nothing else imports it,
// so it's inert until then.
//
// Hog-style console prototype (design spec M1-M4): ordered selection,
// programmer layer, effect editor with transient spread, cuelists with
// tracking, LTP/HTP playback, release, and a provenance value inspector.
// The UI reads resolved output + provenance from the engine and sends
// intents; it never computes effect math itself (spec section 10).

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { LightingEngine } from '../engine/engine.mjs';
import { makeFixture, PARAM_DEFS, defaultEffectAttributes } from '../engine/model.mjs';
import { TABLE_IDS } from '../engine/tables.mjs';

const PARAM_IDS = ['intensity', 'pan', 'tilt', 'red', 'green', 'blue'];
const TABLE_LABELS = {
  sine: 'Sine', tangent: 'Tangent', sawtooth: 'Saw', ramp: 'Ramp',
  inverseRamp: 'Inv Ramp', step: 'Step', markOn: 'Mark On', markOff: 'Mark Off',
  spiral: 'Spiral', random1: 'Rnd Low', random2: 'Rnd High', random3: 'Rnd Mid',
};

function fmt(v, def) {
  if (v == null) return '—';
  const n = Math.round(v * 10) / 10;
  return def.units === 'degrees' ? n + '°' : n + '%';
}

function ownerLabel(owner) {
  if (!owner) return '—';
  if (owner.type === 'programmer') return 'PROG';
  if (owner.type === 'playback') return 'PB' + owner.playbackId + (owner.cueNumber != null ? ' Q' + owner.cueNumber : '') + (owner.htp ? ' HTP' : '');
  if (owner.type === 'release') return 'REL';
  return 'dflt';
}

const OWNER_COLOR = {
  programmer: '#f59e0b', playback: '#3b82f6', release: '#a855f7', default: '#4b5563',
};

// ─── Stage canvas: renders resolved engine output, never computes math ───
function Stage({ outputsRef, fixtures, onPick, picked }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let raf;
    const draw = () => {
      const W = canvas.width, H = canvas.height;
      ctx.fillStyle = '#0a0f1a';
      ctx.fillRect(0, 0, W, H);
      ctx.strokeStyle = '#111827';
      for (let i = 1; i < 4; i++) {
        ctx.beginPath(); ctx.moveTo((W / 4) * i, 0); ctx.lineTo((W / 4) * i, H); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0, (H / 4) * i); ctx.lineTo(W, (H / 4) * i); ctx.stroke();
      }
      const outputs = outputsRef.current;
      if (outputs) {
        fixtures.forEach((fix) => {
          const get = (pid) => outputs.get(fix.id + ':' + pid);
          const int = get('intensity');
          const intensity = int ? int.value / 100 : 0;
          const pan = get('pan'), tilt = get('tilt');
          const x = pan ? ((pan.value + 270) / 540) * W : W / 2;
          const y = tilt ? ((tilt.value + 135) / 270) * H : H / 2;
          const r = get('red'), g = get('green'), b = get('blue');
          const ri = r ? Math.round(r.value * 2.55) : 255;
          const gi = g ? Math.round(g.value * 2.55) : 255;
          const bi = b ? Math.round(b.value * 2.55) : 255;
          const radius = 6 + intensity * 12;
          if (intensity > 0.01) {
            const grd = ctx.createRadialGradient(x, y, 0, x, y, radius * 2.5);
            grd.addColorStop(0, 'rgba(' + ri + ',' + gi + ',' + bi + ',' + (intensity * 0.55).toFixed(3) + ')');
            grd.addColorStop(1, 'rgba(' + ri + ',' + gi + ',' + bi + ',0)');
            ctx.beginPath(); ctx.arc(x, y, radius * 2.5, 0, Math.PI * 2);
            ctx.fillStyle = grd; ctx.fill();
            ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(' + ri + ',' + gi + ',' + bi + ',' + intensity.toFixed(3) + ')';
            ctx.fill();
          } else {
            ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2);
            ctx.strokeStyle = 'rgba(120,120,120,0.35)'; ctx.stroke();
          }
          if (picked === fix.id) {
            ctx.beginPath(); ctx.arc(x, y, radius + 5, 0, Math.PI * 2);
            ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 1.5; ctx.stroke(); ctx.lineWidth = 1;
          }
          ctx.fillStyle = 'rgba(255,255,255,0.6)';
          ctx.font = 'bold 9px monospace';
          ctx.textAlign = 'center';
          ctx.fillText('#' + fix.number, x, y + radius + 11);
          fix._sx = x; fix._sy = y;
        });
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [outputsRef, fixtures, picked]);

  const handleClick = (e) => {
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) * (canvas.width / rect.width);
    const y = (e.clientY - rect.top) * (canvas.height / rect.height);
    let best = null, bd = 30;
    fixtures.forEach((f) => {
      const d = Math.hypot(x - (f._sx ?? -99), y - (f._sy ?? -99));
      if (d < bd) { bd = d; best = f.id; }
    });
    if (best) onPick(best);
  };

  return <canvas ref={canvasRef} width={340} height={260} onClick={handleClick} className="w-full rounded-lg cursor-pointer" />;
}

const btn = 'px-2 py-1 text-[9px] font-bold tracking-widest rounded-sm border transition-colors';
const btnIdle = btn + ' bg-[#141414] border-[#2a2a2a] text-text-muted hover:border-border';
const btnAmber = btn + ' bg-amber-950/40 border-amber-700 text-warn';
const btnBlue = btn + ' bg-brand-dim/40 border-brand text-gel';

function Slider({ label, value, min, max, step = 1, unit = '', onChange, accent = 'accent-brand' }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[8px] text-text-muted uppercase tracking-widest w-14">{label}</span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))} className={'flex-1 ' + accent} />
      <span className="text-[10px] font-mono text-zinc-300 w-12 text-right">{Math.round(value * 10) / 10}{unit}</span>
    </div>
  );
}

export default function Console() {
  const engineRef = useRef(null);
  if (!engineRef.current) {
    const fixtures = Array.from({ length: 6 }, (_, i) => makeFixture(i + 1, 'movingHead'));
    const engine = new LightingEngine(fixtures);
    engine.addPlayback(); // PB1
    engine.addPlayback(); // PB2
    engineRef.current = engine;
  }
  const engine = engineRef.current;

  const [, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((v) => v + 1), []);
  const [, setTick] = useState(0);

  const [editParam, setEditParam] = useState('intensity');
  const [spreadPct, setSpreadPct] = useState(100);
  const [buddy, setBuddy] = useState(1);
  const [inspectId, setInspectId] = useState('1');
  const [cueNumbers, setCueNumbers] = useState({});
  const [cueOnly, setCueOnly] = useState(false);

  const tRef = useRef(0);
  const startRef = useRef(null);
  const outputsRef = useRef(null);

  // Engine clock + per-frame evaluation (canvas + inspector read outputsRef)
  useEffect(() => {
    let raf;
    const loop = (now) => {
      if (!startRef.current) startRef.current = now;
      tRef.current = (now - startRef.current) / 1000;
      outputsRef.current = engine.evaluateFrame(tRef.current);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [engine]);

  // Slow re-render for live numeric readouts
  useEffect(() => {
    const id = setInterval(() => setTick((x) => x + 1), 150);
    return () => clearInterval(id);
  }, []);

  const sel = engine.selection;
  const firstSelKey = sel.length ? sel[0] + ':' + editParam : null;
  const progEntry = firstSelKey ? engine.programmer.get(firstSelKey) : null;
  const curEffect = progEntry && progEntry.effect && progEntry.effect !== 'off' ? progEntry.effect : null;
  const editDef = PARAM_DEFS[editParam];
  const editSpan = editDef.max - editDef.min;

  const setAttr = (patch) => { engine.applyEffect(editParam, patch, tRef.current); bump(); };

  const nextCueNumber = (pb) => {
    const stored = cueNumbers[pb.id];
    if (stored != null) return stored;
    const last = pb.cuelist.cues[pb.cuelist.cues.length - 1];
    return last ? Math.floor(last.number) + 1 : 1;
  };

  const outputs = outputsRef.current;

  return (
    <div className="flex flex-col bg-[#0a0a0a] text-text" style={{ height: 'calc(100vh - 80px)' }}>
      {/* Top bar */}
      <div className="flex items-center gap-4 px-4 py-2 bg-[#0d0d0d] border-b border-[#1c1c1c] flex-shrink-0">
        <h1 className="text-[11px] font-bold tracking-widest text-gel uppercase font-mono">Console</h1>
        <div className="flex items-center gap-2">
          <span className="text-[8px] text-text-muted uppercase tracking-widest">Master Rate</span>
          <input type="range" min="0.1" max="4" step="0.05" value={engine.masterRate}
            onChange={(e) => { engine.masterRate = parseFloat(e.target.value); bump(); }}
            className="w-24 accent-brand" />
          <span className="text-[10px] font-mono text-zinc-300 w-10">{engine.masterRate.toFixed(2)}x</span>
        </div>
        <button onClick={() => { startRef.current = null; }} className={btnIdle}>RESET CLK</button>
        <div className="ml-auto flex items-center gap-3">
          {engine.programmer.size > 0 ? (
            <span className="text-[9px] font-mono text-warn">
              PROGRAMMER · {engine.programmer.size} param{engine.programmer.size > 1 ? 's' : ''} held — Clear to reveal playback
            </span>
          ) : (
            <span className="text-[9px] font-mono text-text-muted">programmer empty — output is playback</span>
          )}
          <button onClick={() => { engine.clearProgrammer(); bump(); }}
            className={engine.programmer.size ? btnAmber : btnIdle}>CLEAR</button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left: fixtures + programmer/effect editor */}
        <div className="flex-1 flex flex-col overflow-y-auto border-r border-[#1c1c1c] min-w-0">

          {/* Fixture selection (ordered) */}
          <div className="px-3 py-2 border-b border-[#1c1c1c]">
            <div className="flex items-center gap-2 mb-1.5">
              <span className="text-[8px] text-text-muted uppercase tracking-widest">Fixtures — selection order drives the fan</span>
              <button className={btnIdle + ' ml-auto'} onClick={() => { engine.setSelection(engine.fixtures.map((f) => f.id)); bump(); }}>ALL</button>
              <button className={btnIdle} onClick={() => { engine.clearSelection(); bump(); }}>NONE</button>
            </div>
            <div className="flex gap-1.5 flex-wrap">
              {engine.fixtures.map((f) => {
                const ord = sel.indexOf(f.id);
                const held = PARAM_IDS.some((p) => engine.programmer.has(f.id + ':' + p));
                return (
                  <button key={f.id} onClick={() => { engine.toggleSelect(f.id); bump(); }}
                    className={'relative w-14 h-12 rounded-sm border text-center ' +
                      (ord !== -1 ? 'border-brand bg-brand-dim/40' : 'border-[#2a2a2a] bg-[#141414] hover:border-border')}>
                    <div className="text-[11px] font-mono font-bold text-text">#{f.number}</div>
                    <div className="text-[7px] text-text-muted">{f.typeName}</div>
                    {ord !== -1 && (
                      <span className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-brand text-[8px] font-bold flex items-center justify-center">{ord + 1}</span>
                    )}
                    {held && <span className="absolute -top-1 -left-1 w-2 h-2 rounded-full bg-warn" title="in programmer" />}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Effect editor */}
          <div className="px-3 py-2 border-b border-[#1c1c1c]">
            <div className="flex items-center gap-1 mb-2">
              <span className="text-[8px] text-text-muted uppercase tracking-widest mr-2">Parameter</span>
              {PARAM_IDS.map((p) => (
                <button key={p} onClick={() => setEditParam(p)}
                  className={editParam === p ? btnBlue : btnIdle}>{PARAM_DEFS[p].name}</button>
              ))}
            </div>

            {sel.length === 0 ? (
              <div className="text-[9px] text-text-muted font-mono py-3">select fixtures to edit</div>
            ) : (
              <div className="space-y-1.5">
                <Slider label={'Base'} unit={editDef.units === 'degrees' ? '°' : '%'}
                  value={progEntry?.base ?? editDef.home} min={editDef.min} max={editDef.max}
                  accent="accent-amber-500"
                  onChange={(v) => { engine.setBase(editParam, v); bump(); }} />

                <div className="flex items-center gap-1 flex-wrap">
                  <span className="text-[8px] text-text-muted uppercase tracking-widest w-14">Table</span>
                  {TABLE_IDS.map((tid) => (
                    <button key={tid}
                      onClick={() => setAttr({ table: tid })}
                      className={curEffect?.table === tid ? btnBlue : btnIdle}>{TABLE_LABELS[tid]}</button>
                  ))}
                  <button onClick={() => { engine.effectOff(editParam); bump(); }}
                    className={progEntry?.effect === 'off' ? btnAmber : btnIdle}
                    title="record an explicit stop for a tracked effect">FX OFF</button>
                  <button onClick={() => { sel.forEach((fid) => engine.knockout(fid, editParam)); bump(); }}
                    className={btnIdle} title="remove this parameter from the programmer">KNOCKOUT</button>
                </div>

                {curEffect && (
                  <>
                    <Slider label="Size" value={curEffect.size} min={0} max={editSpan / 2}
                      unit={editDef.units === 'degrees' ? '°' : '%'}
                      onChange={(v) => setAttr({ size: v })} />
                    <Slider label="Rate" value={curEffect.rate} min={0} max={240} unit=" cpm"
                      onChange={(v) => setAttr({ rate: v })} />
                    <Slider label="Offset" value={curEffect.offset} min={0} max={360} unit="°"
                      onChange={(v) => setAttr({ offset: v })} />
                    <Slider label="Length" value={curEffect.length} min={1} max={100} unit="%"
                      onChange={(v) => setAttr({ length: v })} />
                    <div className="flex items-center gap-3 pt-0.5">
                      <button className={curEffect.direction === 'reverse' ? btnBlue : btnIdle}
                        onClick={() => setAttr({ direction: curEffect.direction === 'reverse' ? 'forward' : 'reverse' })}>
                        DIR {curEffect.direction === 'reverse' ? 'REV' : 'FWD'}
                      </button>
                      <button className={curEffect.bounce ? btnBlue : btnIdle}
                        onClick={() => setAttr({ bounce: !curEffect.bounce })}>BOUNCE</button>
                      <label className="flex items-center gap-1 text-[8px] text-text-muted uppercase tracking-widest">
                        N-Shot
                        <input type="number" min="0" value={curEffect.nShot ?? ''}
                          placeholder="—"
                          onChange={(e) => setAttr({ nShot: e.target.value === '' ? null : parseInt(e.target.value) })}
                          className="w-12 bg-[#141414] border border-[#2a2a2a] rounded-sm px-1 py-0.5 text-[10px] font-mono text-zinc-200" />
                      </label>
                    </div>
                    <div className="flex items-center gap-2 pt-1 border-t border-[#1c1c1c] mt-1">
                      <span className="text-[8px] text-text-muted uppercase tracking-widest">Spread (transient — writes offsets, not stored)</span>
                      <input type="range" min="-100" max="100" step="5" value={spreadPct}
                        onChange={(e) => setSpreadPct(parseInt(e.target.value))} className="w-24 accent-purple-500" />
                      <span className="text-[10px] font-mono text-zinc-300 w-10">{spreadPct}%</span>
                      <label className="flex items-center gap-1 text-[8px] text-text-muted uppercase">
                        Buddy
                        <input type="number" min="1" max="6" value={buddy}
                          onChange={(e) => setBuddy(Math.max(1, parseInt(e.target.value) || 1))}
                          className="w-10 bg-[#141414] border border-[#2a2a2a] rounded-sm px-1 py-0.5 text-[10px] font-mono text-zinc-200" />
                      </label>
                      <button className={btn + ' bg-purple-950/40 border-purple-700 text-purple-300'}
                        onClick={() => { engine.applySpread(editParam, spreadPct, buddy); bump(); }}>APPLY FAN</button>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          {/* Programmer contents */}
          <div className="px-3 py-2">
            <div className="text-[8px] text-text-muted uppercase tracking-widest mb-1">Programmer contents (record source)</div>
            {engine.programmer.size === 0 ? (
              <div className="text-[9px] text-text-muted font-mono">empty</div>
            ) : (
              <div className="flex flex-wrap gap-1">
                {[...engine.programmer.entries()].map(([key, v]) => {
                  const [fid, pid] = [key.split(':')[0], key.split(':').slice(1).join(':')];
                  return (
                    <span key={key} className="text-[8px] font-mono px-1.5 py-0.5 rounded-sm bg-amber-950/30 border border-amber-900/60 text-warn">
                      #{fid} {pid}
                      {v.base != null && ' B' + Math.round(v.base)}
                      {v.effect === 'off' ? ' FX-OFF' : v.effect ? ' ~' + TABLE_LABELS[v.effect.table] : ''}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right: playbacks + stage + inspector */}
        <div className="w-[430px] flex flex-col overflow-y-auto flex-shrink-0">

          {/* Playback masters */}
          {engine.playbacks.map((pb) => (
            <div key={pb.id} className="border-b border-[#1c1c1c] px-3 py-2">
              <div className="flex items-center gap-2 mb-1">
                <span className={'text-[9px] font-bold tracking-widest font-mono ' + (pb.active ? 'text-gel' : 'text-text-muted')}>
                  PB{pb.id} · {pb.cuelist.name}
                </span>
                {pb.active && pb.currentCueIndex >= 0 && (
                  <span className="text-[8px] font-mono text-gel bg-brand-dim/40 px-1 rounded-sm">
                    in Q{pb.cuelist.cues[pb.currentCueIndex]?.number}
                  </span>
                )}
                <label className="ml-auto flex items-center gap-1 text-[8px] text-text-muted uppercase tracking-widest cursor-pointer">
                  <input type="checkbox" checked={pb.cuelist.htpIntensity}
                    onChange={(e) => { pb.cuelist.htpIntensity = e.target.checked; bump(); }} className="accent-brand" />
                  HTP int
                </label>
                <label className="flex items-center gap-1 text-[8px] text-text-muted uppercase tracking-widest">
                  Rel
                  <input type="number" min="0" step="0.5" value={pb.cuelist.releaseTime}
                    onChange={(e) => { pb.cuelist.releaseTime = parseFloat(e.target.value) || 0; bump(); }}
                    className="w-10 bg-[#141414] border border-[#2a2a2a] rounded-sm px-1 text-[9px] font-mono text-zinc-200" />s
                </label>
              </div>

              {/* Cue rows */}
              <div className="space-y-0.5 mb-1.5">
                {pb.cuelist.cues.length === 0 && (
                  <div className="text-[8px] text-text-muted font-mono">no cues — build a look, then RECORD</div>
                )}
                {pb.cuelist.cues.map((cue, ci) => (
                  <div key={cue.id}
                    onClick={() => { engine.goToCue(pb.id, cue.number, tRef.current); bump(); }}
                    className={'flex items-center gap-2 px-1.5 py-0.5 rounded-sm cursor-pointer border ' +
                      (pb.active && ci === pb.currentCueIndex
                        ? 'border-brand bg-brand-dim/30'
                        : 'border-transparent hover:border-[#2a2a2a]')}>
                    <span className="text-[10px] font-mono font-bold text-text-muted w-8">Q{cue.number}</span>
                    <div className="flex flex-wrap gap-1 flex-1">
                      {cue.hardValues.map((hv, i) => (
                        <span key={i} className="text-[7px] font-mono px-1 rounded-sm bg-[#141414] border border-[#2a2a2a] text-text-muted"
                          title="hard values stored in this cue — everything else tracks">
                          #{hv.fixtureId} {hv.parameterId}
                          {hv.base != null && ' B' + Math.round(hv.base)}
                          {hv.effect === 'off' ? ' OFF' : hv.effect ? ' ~' + (TABLE_LABELS[hv.effect.table] || hv.effect.table) : ''}
                        </span>
                      ))}
                    </div>
                    <button className="text-[8px] text-red-800 hover:text-brand-hi font-bold"
                      onClick={(e) => { e.stopPropagation(); pb.cuelist.cues.splice(ci, 1); if (pb.currentCueIndex >= pb.cuelist.cues.length) pb.currentCueIndex = pb.cuelist.cues.length - 1; bump(); }}
                      title="delete cue — later cues that tracked its values WILL change">✕</button>
                  </div>
                ))}
              </div>

              {/* Transport + record */}
              <div className="flex items-center gap-1.5">
                <button className={btn + ' bg-surface/40 border-online text-online px-3'}
                  onClick={() => { engine.go(pb.id, tRef.current); bump(); }}>GO</button>
                <button className={btnIdle} onClick={() => { engine.back(pb.id, tRef.current); bump(); }}>BACK</button>
                <button className={btn + ' bg-purple-950/40 border-purple-800 text-purple-400'}
                  onClick={() => { engine.release(pb.id, tRef.current); bump(); }}>RELEASE</button>
                <span className="ml-auto flex items-center gap-1">
                  <span className="text-[8px] text-text-muted uppercase">Q</span>
                  <input type="number" step="0.1" min="0" value={nextCueNumber(pb)}
                    onChange={(e) => setCueNumbers({ ...cueNumbers, [pb.id]: parseFloat(e.target.value) })}
                    className="w-12 bg-[#141414] border border-[#2a2a2a] rounded-sm px-1 py-0.5 text-[10px] font-mono text-zinc-200" />
                  <button
                    className={engine.programmer.size ? btn + ' bg-brand-dim/50 border-brand text-brand-hi' : btnIdle}
                    disabled={!engine.programmer.size}
                    title={cueOnly ? 'record contained to this cue (auto-Off into the next)' : 'record; values track forward until changed'}
                    onClick={() => {
                      engine.record(pb.id, nextCueNumber(pb), { cueOnly });
                      const n = { ...cueNumbers }; delete n[pb.id]; setCueNumbers(n);
                      bump();
                    }}>RECORD</button>
                  <label className="flex items-center gap-0.5 text-[7px] text-text-muted uppercase cursor-pointer">
                    <input type="checkbox" checked={cueOnly} onChange={(e) => setCueOnly(e.target.checked)} className="accent-amber-500" />
                    cue only
                  </label>
                </span>
              </div>
            </div>
          ))}

          {/* Stage */}
          <div className="border-b border-[#1c1c1c] px-3 py-2">
            <div className="text-[8px] text-text-muted uppercase tracking-widest mb-1">Stage — click a fixture to inspect</div>
            <Stage outputsRef={outputsRef} fixtures={engine.fixtures} onPick={setInspectId} picked={inspectId} />
          </div>

          {/* Value inspector: output + provenance */}
          <div className="px-3 py-2">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[8px] text-text-muted uppercase tracking-widest">Inspector</span>
              {engine.fixtures.map((f) => (
                <button key={f.id} onClick={() => setInspectId(f.id)}
                  className={'text-[9px] font-mono px-1.5 rounded-sm border ' +
                    (inspectId === f.id ? 'border-amber-600 text-warn bg-amber-950/30' : 'border-[#2a2a2a] text-text-muted hover:border-border')}>
                  #{f.number}
                </button>
              ))}
            </div>
            <table className="w-full text-[9px] font-mono">
              <thead>
                <tr className="text-text-muted text-left">
                  <th className="font-normal uppercase tracking-widest text-[7px] py-0.5">Param</th>
                  <th className="font-normal uppercase tracking-widest text-[7px]">Value</th>
                  <th className="font-normal uppercase tracking-widest text-[7px]">Base</th>
                  <th className="font-normal uppercase tracking-widest text-[7px]">Swing</th>
                  <th className="font-normal uppercase tracking-widest text-[7px]">Owner</th>
                  <th className="font-normal uppercase tracking-widest text-[7px]">From</th>
                </tr>
              </thead>
              <tbody>
                {PARAM_IDS.map((pid) => {
                  const out = outputs?.get(inspectId + ':' + pid);
                  if (!out) return null;
                  const def = PARAM_DEFS[pid];
                  const oc = OWNER_COLOR[out.owner.type] || '#4b5563';
                  const prov = [];
                  if (out.provenance?.baseFrom != null) {
                    const tracked = out.owner.cueNumber != null && out.provenance.baseFrom !== out.owner.cueNumber;
                    prov.push('B←Q' + out.provenance.baseFrom + (tracked ? ' (trk)' : ''));
                  }
                  if (out.effect && out.provenance?.effectFrom != null) {
                    const tracked = out.owner.cueNumber != null && out.provenance.effectFrom !== out.owner.cueNumber;
                    prov.push('FX←Q' + out.provenance.effectFrom + (tracked ? ' (trk)' : ''));
                  }
                  return (
                    <tr key={pid} className="border-t border-[#161616]">
                      <td className="py-0.5 text-text-muted">{def.name}</td>
                      <td className="text-zinc-100 font-bold">{fmt(out.value, def)}</td>
                      <td className="text-text-muted">{fmt(out.base, def)}</td>
                      <td className="text-text-muted">
                        {out.effect ? (out.swing >= 0 ? '+' : '') + (Math.round(out.swing * 10) / 10) : '—'}
                        {out.effect && <span className="text-gel"> ~{TABLE_LABELS[out.effect.table] || out.effect.table}</span>}
                      </td>
                      <td><span style={{ color: oc }}>{ownerLabel(out.owner)}</span></td>
                      <td className="text-text-muted">{prov.join(' ') || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="text-[7px] text-text-muted mt-1 font-mono">
              trk = tracked in from an earlier cue · PROG overrides playback · Clear reveals what playback is doing
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
