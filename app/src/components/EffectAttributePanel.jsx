import React, { useEffect, useRef, useCallback } from 'react';
import { computeEffect } from '../utils/effectMath';

const TABLES = [
  { id: 'sine',        label: 'Sine' },
  { id: 'tangent',     label: 'Tangent' },
  { id: 'sawtooth',    label: 'Sawtooth' },
  { id: 'ramp',        label: 'Ramp' },
  { id: 'inverseRamp', label: 'Inv Ramp' },
  { id: 'step',        label: 'Step' },
  { id: 'markOn',      label: 'Mark On' },
  { id: 'markOff',     label: 'Mark Off' },
  { id: 'spiral',      label: 'Spiral' },
  { id: 'random1',     label: 'Rnd Low' },
  { id: 'random2',     label: 'Rnd High' },
  { id: 'random3',     label: 'Rnd Mid' },
];

const TABLE_INFO = {
  sine:        { desc: 'Smooth S-curve — eases in and out at every peak. Acceleration is zero at the extremes.', use: 'Circles, breathing, color fades, organic motion.' },
  tangent:     { desc: 'Slow through center, snaps very fast near edges. Creates a "crack-the-whip" feel.', use: 'Pan snap moves, dramatic intensity flashes.' },
  sawtooth:    { desc: 'Linear ramp up, then instant snap back. One direction → snap → repeat.', use: 'Directional chases, spin effects, continuous sweeps.' },
  ramp:        { desc: 'Linear increase from low to high across the full cycle. No snap — just a steady climb.', use: 'Build effects, ascending chases, slow rises.' },
  inverseRamp: { desc: 'Linear decrease from high to low across the cycle.', use: 'Fade-down effects, descending chases.' },
  step:        { desc: 'Hard cut between high and low — zero transition time. Pure square wave.', use: 'Hard-cut chases, strobe, square pan sweeps.' },
  markOn:      { desc: 'Holds fully ON for the active Length portion, then snaps back to base.', use: 'Beat pulses. Shorten Length for a quick hit.' },
  markOff:     { desc: 'Holds fully OFF for the active Length portion, then snaps back to base.', use: 'Dip/blackout pulses on a beat, dropout accents.' },
  spiral:      { desc: 'Double-tangent: two snap moments per cycle. Lingers at center, snaps to each extreme.', use: 'Double-hit pan snaps, "zip-zap" moves, rapid whips.' },
  random1:     { desc: 'Random values biased toward the BOTTOM of the range (below base).', use: 'Dim-biased flicker — candle, embers, distant stars.' },
  random2:     { desc: 'Random values biased toward the TOP of the range (above base).', use: 'Bright-biased sparkle — star field, glitter, camera flash.' },
  random3:     { desc: 'Random values clustered near base — very subtle variation.', use: 'Gentle color drift, soft shimmer, naturalistic breathing.' },
};

// ─── Encoder Wheel ────────────────────────────────────────────────────────────
function Encoder({ label, unit, value, min, max, step = 1, disabled, onChange, color = '#3b82f6' }) {
  const SIZE = 62;
  const cx = SIZE / 2, cy = SIZE / 2, r = 23;

  const normalized = (value != null && max > min)
    ? Math.max(0, Math.min(1, (value - min) / (max - min)))
    : 0;

  const toXY = (deg) => ({
    x: +(cx + r * Math.sin(deg * Math.PI / 180)).toFixed(2),
    y: +(cy - r * Math.cos(deg * Math.PI / 180)).toFixed(2),
  });

  const startPt  = toXY(-135);
  const endPt    = toXY(135);
  const curAngle = -135 + normalized * 270;
  const curPt    = toXY(curAngle);
  const span     = normalized * 270;
  const bigArc   = span > 180 ? 1 : 0;

  const trackD  = `M${startPt.x} ${startPt.y} A${r} ${r} 0 1 1 ${endPt.x} ${endPt.y}`;
  const activeD = span > 0
    ? `M${startPt.x} ${startPt.y} A${r} ${r} 0 ${bigArc} 1 ${curPt.x} ${curPt.y}`
    : null;

  const stateRef = useRef({ value, min, max, step, onChange });
  stateRef.current = { value, min, max, step, onChange };

  const elRef = useRef(null);

  const handleMouseDown = useCallback((e) => {
    if (disabled) return;
    e.preventDefault();
    const { value: sv, min: lo, max: hi, step: st, onChange: cb } = stateRef.current;
    if (sv == null) return;
    const startY = e.clientY;
    const range  = hi - lo;
    const onMove = (ev) => {
      const dy  = startY - ev.clientY;
      const raw = Math.max(lo, Math.min(hi, sv + dy * (range / 200)));
      cb(Math.round(raw / st) * st);
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [disabled]);

  useEffect(() => {
    const el = elRef.current;
    if (!el) return;
    const onWheel = (e) => {
      if (disabled) return;
      const { value: v, min: lo, max: hi, step: st, onChange: cb } = stateRef.current;
      if (v == null) return;
      e.preventDefault();
      const dir = e.deltaY < 0 ? 1 : -1;
      cb(Math.max(lo, Math.min(hi, Math.round((v + dir * st) / st) * st)));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [disabled]);

  const hasVal = value != null && !disabled;

  return (
    <div className="flex flex-col items-center gap-0.5 select-none">
      <div
        ref={elRef}
        onMouseDown={handleMouseDown}
        className={`relative ${disabled ? 'opacity-20 cursor-not-allowed' : 'cursor-ns-resize hover:brightness-125'}`}
        style={{ width: SIZE, height: SIZE }}
        title={disabled ? '' : 'Drag ↑↓ or scroll wheel'}
      >
        <svg width={SIZE} height={SIZE}>
          <circle cx={cx} cy={cy} r={r + 5} fill="#0c0c0c" />
          <path d={trackD} fill="none" stroke="#222" strokeWidth="5" strokeLinecap="round" />
          {activeD && (
            <path d={activeD} fill="none" stroke={hasVal ? color : '#333'} strokeWidth="5" strokeLinecap="round" />
          )}
          {hasVal && span > 0 && (
            <circle cx={curPt.x} cy={curPt.y} r={3.5} fill="white" opacity={0.9} />
          )}
          <circle cx={cx} cy={cy} r={8} fill="#181818" stroke="#2a2a2a" strokeWidth={1} />
        </svg>
      </div>
      <div className={`text-[11px] font-mono tabular-nums leading-tight ${hasVal ? 'text-zinc-100' : 'text-gray-700'}`}>
        {hasVal ? `${value}${unit || ''}` : '─'}
      </div>
      <div className="text-[8px] text-gray-600 uppercase tracking-widest leading-none">{label}</div>
    </div>
  );
}

// ─── Wave Preview ─────────────────────────────────────────────────────────────
function WavePreview({ params }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;

    ctx.fillStyle = '#080808';
    ctx.fillRect(0, 0, W, H);

    if (!params?.table) {
      ctx.fillStyle = '#2a2a2a';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('No effect', W / 2, H / 2 + 4);
      return;
    }

    const size = params.size ?? 50;
    const halfRange = (size / 100) / 2;
    const minRaw = 0.5 - halfRange, maxRaw = 0.5 + halfRange;
    const clipsTop = maxRaw > 1, clipsBot = minRaw < 0;
    const pad = 0.1;
    const viewMin = Math.min(minRaw, 0) - pad;
    const viewMax = Math.max(maxRaw, 1) + pad;
    const viewRange = viewMax - viewMin;
    const toY = (v) => H - ((v - viewMin) / viewRange) * H;

    if (clipsTop) { ctx.fillStyle = 'rgba(239,68,68,0.07)'; ctx.fillRect(0, 0, W, toY(1)); }
    if (clipsBot) { ctx.fillStyle = 'rgba(239,68,68,0.07)'; ctx.fillRect(0, toY(0), W, H - toY(0)); }

    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, toY(1)); ctx.lineTo(W, toY(1)); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, toY(0)); ctx.lineTo(W, toY(0)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    ctx.beginPath(); ctx.moveTo(0, toY(0.5)); ctx.lineTo(W, toY(0.5)); ctx.stroke();

    const cycleDuration = 60 / (params.rate || 60);
    const pts = Array.from({ length: W + 1 }, (_, x) => ({
      x, raw: computeEffect(params.table, (x / W) * cycleDuration, params),
    }));

    for (let i = 0; i < pts.length - 1; i++) {
      const { x, raw } = pts[i];
      const next = pts[i + 1];
      ctx.strokeStyle = (raw > 1 || raw < 0) ? 'rgba(239,68,68,0.85)' : '#3b82f6';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x, toY(raw));
      ctx.lineTo(next.x, toY(next.raw));
      ctx.stroke();
    }

    if (clipsTop || clipsBot) {
      ctx.fillStyle = 'rgba(239,68,68,0.8)';
      ctx.font = 'bold 7px sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText('CLIP', W - 3, 8);
    }
  }, [params]);

  return <canvas ref={canvasRef} width={200} height={58} className="w-full rounded" />;
}

// ─── Hog-style toggle button ──────────────────────────────────────────────────
function HogBtn({ active, disabled, onClick, color = '#2563eb', children }) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className={`px-2.5 py-1.5 text-[9px] font-bold tracking-widest rounded-sm border transition-all leading-none ${
        active
          ? 'text-white'
          : 'bg-[#141414] border-[#2a2a2a] text-gray-500 hover:text-gray-300 hover:border-[#444]'
      } disabled:opacity-15 disabled:cursor-not-allowed`}
      style={active ? { backgroundColor: color, borderColor: color, boxShadow: `0 0 8px ${color}55` } : {}}
    >
      {children}
    </button>
  );
}

// ─── Main Panel ───────────────────────────────────────────────────────────────
export default function EffectAttributePanel({
  selectedCells, fixtures, defaultBases, onUpdateCells, onUpdateBase, onClearCells,
  onApplySpread, spread, onSpreadChange,
}) {
  const firstCell = [...selectedCells][0];
  let currentParam = null;
  let currentBase  = null;
  if (firstCell) {
    const [fi, pk] = firstCell.split(':');
    const fix = fixtures[parseInt(fi)];
    currentParam = fix?.params[pk] || null;
    currentBase  = Math.round((fix?.bases?.[pk] ?? defaultBases?.[pk] ?? 1.0) * 100);
  }

  const hasSelection = selectedCells.size > 0;
  const val = (field, def) => currentParam?.[field] ?? def;
  const activeTable = currentParam?.table;

  const rangeInfo = (() => {
    if (currentBase === null || !activeTable) return null;
    const base = currentBase / 100;
    const halfRange = (val('size', 50) / 100) / 2;
    const rawLow  = base - halfRange;
    const rawHigh = base + halfRange;
    return {
      low:  Math.round(Math.max(0, rawLow)  * 100),
      high: Math.round(Math.min(1, rawHigh) * 100),
      base: currentBase,
      clipsLow:  rawLow  < 0,
      clipsHigh: rawHigh > 1,
    };
  })();

  const lengthPct = val('length', 100);

  return (
    <div className="bg-[#0a0a0a] border-t-2 border-[#1c1c1c] px-3 py-2">
      <div className="flex gap-4 items-start flex-wrap">

        {/* ── Wave Table Selector ────────────────────────────────────────── */}
        <div className="flex-shrink-0">
          <div className="text-[8px] text-gray-600 uppercase tracking-widest mb-1.5">Table</div>
          <div className="grid grid-cols-3 gap-0.5 w-44">
            {TABLES.map(t => (
              <button
                key={t.id}
                disabled={!hasSelection}
                onClick={() => onUpdateCells('table', t.id)}
                className={`py-1.5 text-[9px] font-medium rounded-sm transition-all leading-none border ${
                  activeTable === t.id
                    ? 'bg-blue-600 border-blue-500 text-white shadow-[0_0_6px_rgba(59,130,246,0.4)]'
                    : 'bg-[#141414] border-[#252525] text-gray-400 hover:bg-[#1e1e1e] hover:text-gray-200 disabled:opacity-15 disabled:cursor-not-allowed'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* ── Encoder Wheels ─────────────────────────────────────────────── */}
        <div className="flex-shrink-0 flex flex-col gap-1">
          <div className="text-[8px] text-gray-600 uppercase tracking-widest">Parameters</div>
          <div className="flex items-center gap-1">
            <Encoder
              label="Base" unit="%" color="#f59e0b"
              value={hasSelection ? currentBase : null}
              min={0} max={100} step={1} disabled={!hasSelection}
              onChange={v => onUpdateBase(v)}
            />
            {/* Divider */}
            <div className="w-px self-stretch mx-1 bg-[#1e1e1e]" />
            <Encoder
              label="Rate" unit=" cpm" color="#3b82f6"
              value={hasSelection ? val('rate', 60) : null}
              min={1} max={600} step={1} disabled={!hasSelection}
              onChange={v => onUpdateCells('rate', v)}
            />
            <Encoder
              label="Size" unit="%" color="#22c55e"
              value={hasSelection ? val('size', 50) : null}
              min={0} max={400} step={1} disabled={!hasSelection}
              onChange={v => onUpdateCells('size', v)}
            />
            <Encoder
              label="Offset" unit="°" color="#a855f7"
              value={hasSelection ? val('offset', 0) : null}
              min={0} max={359} step={1} disabled={!hasSelection}
              onChange={v => onUpdateCells('offset', v)}
            />
            <Encoder
              label="Length" unit="%" color="#06b6d4"
              value={hasSelection ? val('length', 100) : null}
              min={1} max={100} step={1} disabled={!hasSelection}
              onChange={v => onUpdateCells('length', v)}
            />
          </div>
        </div>

        {/* ── Modifiers ──────────────────────────────────────────────────── */}
        <div className="flex flex-col gap-1.5 flex-shrink-0">
          <div className="text-[8px] text-gray-600 uppercase tracking-widest">Modifiers</div>
          <HogBtn
            active={val('bounce', false)} disabled={!hasSelection}
            onClick={() => onUpdateCells('bounce', !val('bounce', false))}
            color="#2563eb"
          >
            BNCE
          </HogBtn>
          <HogBtn
            active={val('direction', 'forward') === 'reverse'} disabled={!hasSelection}
            onClick={() => onUpdateCells('direction', val('direction', 'forward') === 'forward' ? 'reverse' : 'forward')}
            color="#ea580c"
          >
            {val('direction', 'forward') === 'reverse' ? '◀ REV' : '▶ FWD'}
          </HogBtn>
          <div className="flex flex-col gap-0.5 mt-0.5">
            <div className="text-[8px] text-gray-600 uppercase tracking-widest">N-Shot</div>
            <input
              type="number" min={1} placeholder="∞"
              value={val('nShot', null) ?? ''}
              disabled={!hasSelection}
              onChange={e => onUpdateCells('nShot', e.target.value === '' ? null : Number(e.target.value))}
              className="w-14 px-2 py-1 bg-[#141414] border border-[#252525] rounded-sm text-zinc-200 text-[11px] font-mono text-center focus:border-blue-600 focus:outline-none disabled:opacity-20"
            />
          </div>
        </div>

        {/* ── Spread / Fan ───────────────────────────────────────────────── */}
        <div className="flex flex-col gap-1.5 flex-shrink-0 w-28">
          <div className="text-[8px] text-gray-600 uppercase tracking-widest">Fan / Spread</div>
          <input
            type="range" min="0" max="360" step="1"
            value={spread}
            onChange={e => onSpreadChange(Number(e.target.value))}
            className="w-full accent-purple-500"
          />
          <div className="flex justify-between text-[9px]">
            <span className="text-gray-700">0°</span>
            <span className="text-purple-400 font-mono">{spread}°</span>
            <span className="text-gray-700">360°</span>
          </div>
          <HogBtn disabled={!hasSelection} onClick={onApplySpread} color="#7c3aed">
            APPLY FAN
          </HogBtn>
        </div>

        {/* ── Waveform + Educational ─────────────────────────────────────── */}
        <div className="flex flex-col gap-1 flex-shrink-0 w-52">
          <div className="text-[8px] text-gray-600 uppercase tracking-widest">Waveform</div>
          <WavePreview params={currentParam} />

          {/* Swing bar */}
          {rangeInfo && (
            <div>
              <div className="flex justify-between text-[9px] mb-0.5">
                <span className={`font-mono ${rangeInfo.clipsLow ? 'text-red-400' : 'text-blue-400'}`}>
                  {rangeInfo.low}%{rangeInfo.clipsLow ? ' ⚠' : ''}
                </span>
                <span className="text-gray-700 text-[8px]">swing</span>
                <span className={`font-mono ${rangeInfo.clipsHigh ? 'text-red-400' : 'text-blue-400'}`}>
                  {rangeInfo.clipsHigh ? '⚠ ' : ''}{rangeInfo.high}%
                </span>
              </div>
              <div className="relative w-full h-2 bg-[#111] rounded overflow-hidden">
                <div className="absolute top-0 h-full bg-blue-600/35 rounded"
                  style={{ left: `${rangeInfo.low}%`, width: `${rangeInfo.high - rangeInfo.low}%` }} />
                {rangeInfo.clipsLow  && <div className="absolute top-0 left-0 h-full w-0.5 bg-red-500" />}
                {rangeInfo.clipsHigh && <div className="absolute top-0 right-0 h-full w-0.5 bg-red-500" />}
                <div className="absolute top-0 w-px h-full bg-amber-400/60" style={{ left: `${rangeInfo.base}%` }} />
              </div>
              <div className="text-[8px] text-gray-700 text-center mt-0.5">
                base <span className="text-amber-600">{rangeInfo.base}%</span>
                {(rangeInfo.clipsLow || rangeInfo.clipsHigh) && <span className="text-red-500 ml-1">clips</span>}
              </div>
            </div>
          )}

          {/* Length bar */}
          {activeTable && (
            <div>
              <div className="flex justify-between text-[9px] mb-0.5">
                <span className="text-gray-700 text-[8px] uppercase tracking-wide">Length</span>
                <span className="text-cyan-600 font-mono text-[8px]">{lengthPct}% active</span>
              </div>
              <div className="relative w-full h-2 rounded overflow-hidden bg-[#111] flex">
                <div className="h-full bg-cyan-700/55" style={{ width: `${lengthPct}%` }} />
                <div className="h-full bg-[#141414]" style={{ width: `${100 - lengthPct}%` }} />
                {lengthPct < 100 && (
                  <div className="absolute top-0 w-px h-full bg-gray-500/40" style={{ left: `${lengthPct}%` }} />
                )}
              </div>
            </div>
          )}

          {/* Educational section */}
          {activeTable && (() => {
            const size   = val('size',   50);
            const rate   = val('rate',   60);
            const offset = val('offset', 0);
            const bounce = val('bounce', false);
            const secsPerCycle = (60 / rate).toFixed(1);
            const info = TABLE_INFO[activeTable];

            const tips = [
              bounce && 'Bounce: wave reverses each cycle instead of resetting.',
              lengthPct < 70 && `Length ${lengthPct}%: effect fires for ${(secsPerCycle * lengthPct / 100).toFixed(1)}s then holds at base.`,
              size > 100 && 'Size >100%: output clips at 0–100% — creates flat-topped peaks.',
              rate <= 10 && `${rate} CPM = ${secsPerCycle}s/cycle — slow, sweeping motion.`,
              rate >= 150 && `${rate} CPM — rapid flicker territory.`,
              (offset === 90 || offset === 270) && '90° offset from a perpendicular axis → circular motion.',
            ].filter(Boolean);

            return (
              <div className="mt-0.5 space-y-1">
                <div className="bg-[#0d0d0d] border border-[#1e1e1e] rounded px-2 py-1 font-mono text-[8px] leading-relaxed">
                  <span className="text-gray-600">out =</span>{' '}
                  <span className="text-amber-400/80">base</span>{' '}
                  <span className="text-gray-600">±</span>{' '}
                  <span className="text-blue-400">{activeTable}</span>
                  <span className="text-gray-600">(t) ×</span>{' '}
                  <span className="text-green-400">{(size / 2).toFixed(0)}%</span>
                  <div className="text-gray-700">t = (sec×{rate}/60 + {offset}/360) mod 1</div>
                </div>
                {info && (
                  <div className="bg-[#0d0d14] border border-indigo-900/25 rounded px-2 py-1 text-[8px] leading-relaxed">
                    <div className="text-indigo-300/90">{info.desc}</div>
                    <div className="text-indigo-700 mt-0.5">→ {info.use}</div>
                  </div>
                )}
                {tips.length > 0 && (
                  <div className="space-y-0.5">
                    {tips.map((tip, i) => (
                      <div key={i} className="flex gap-1 text-[8px] text-purple-400/65">
                        <span className="text-purple-700 flex-shrink-0">✦</span>
                        <span>{tip}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })()}
        </div>

        {/* ── Actions ────────────────────────────────────────────────────── */}
        <div className="ml-auto flex flex-col gap-2 flex-shrink-0 self-center">
          <HogBtn disabled={!hasSelection} onClick={onClearCells} color="#991b1b">
            CLEAR
          </HogBtn>
          <div className="text-[9px] text-gray-700 text-center font-mono">
            {selectedCells.size} sel
          </div>
        </div>

      </div>
    </div>
  );
}
