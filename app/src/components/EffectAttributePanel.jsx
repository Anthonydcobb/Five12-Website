import React, { useEffect, useRef } from 'react';
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
  tangent:     { desc: 'Moves slowly through center but snaps very fast near the edges. Creates a "crack-the-whip" feel.', use: 'Pan snap moves, dramatic intensity flashes.' },
  sawtooth:    { desc: 'Linear ramp up, then instant reset back. One direction → snap → repeat.', use: 'Directional chases, spin effects, continuous sweeps.' },
  ramp:        { desc: 'Linear increase from low to high across the full cycle. No snap — just a steady climb.', use: 'Build effects, ascending chases, slow rises.' },
  inverseRamp: { desc: 'Linear decrease from high to low across the cycle.', use: 'Fade-down effects, descending chases.' },
  step:        { desc: 'Hard cut between high and low — zero transition time. Pure square wave.', use: 'Hard-cut chases, strobe, square pan sweeps.' },
  markOn:      { desc: 'Holds fully ON for the active Length portion, then snaps back to base. Think: a top-hat pulse.', use: 'Beat pulses. Shorten Length for a quick hit — lengthen for a sustained peak.' },
  markOff:     { desc: 'Holds fully OFF for the active Length portion, then snaps back to base. The inverse of Mark On.', use: 'Dip/blackout pulses on a beat, dropout accents.' },
  spiral:      { desc: 'Two tangent curves per cycle: lingers at center, snaps to +extreme, returns to center, snaps to −extreme. Two hits per cycle.', use: 'Double-hit pan snaps, "zip-zap" moves, rapid whips.' },
  random1:     { desc: 'Random values biased toward the BOTTOM of the range (below base). More low values than high.', use: 'Dim-biased flicker — candle, embers, distant stars.' },
  random2:     { desc: 'Random values biased toward the TOP of the range (above base). More bright hits than dips.', use: 'Bright-biased sparkle — star field, glitter, camera flash.' },
  random3:     { desc: 'Random values clustered near the base — very subtle variation. Almost feels like natural breathing.', use: 'Gentle color drift, soft intensity shimmer, naturalistic life.' },
};

function WavePreview({ params }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;

    ctx.fillStyle = '#111827';
    ctx.fillRect(0, 0, W, H);

    if (!params?.table) {
      ctx.fillStyle = '#4b5563';
      ctx.font = '11px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('No effect', W / 2, H / 2 + 4);
      return;
    }

    const size = params.size ?? 50;
    const halfRange = (size / 100) / 2;
    const minRaw = 0.5 - halfRange;
    const maxRaw = 0.5 + halfRange;
    const clipsTop = maxRaw > 1;
    const clipsBot = minRaw < 0;
    const hasClip = clipsTop || clipsBot;

    // Scale y-axis to show full unclipped wave + padding
    const pad = 0.1;
    const viewMin = Math.min(minRaw, 0) - pad;
    const viewMax = Math.max(maxRaw, 1) + pad;
    const viewRange = viewMax - viewMin;
    const toY = (v) => H - ((v - viewMin) / viewRange) * H;

    // Clipping zone background (red tint)
    if (clipsTop) {
      ctx.fillStyle = 'rgba(239,68,68,0.12)';
      ctx.fillRect(0, 0, W, toY(1));
    }
    if (clipsBot) {
      ctx.fillStyle = 'rgba(239,68,68,0.12)';
      ctx.fillRect(0, toY(0), W, H - toY(0));
    }

    // 100% and 0% boundary lines
    ctx.strokeStyle = 'rgba(255,255,255,0.18)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(0, toY(1)); ctx.lineTo(W, toY(1)); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, toY(0)); ctx.lineTo(W, toY(0)); ctx.stroke();
    ctx.setLineDash([]);

    // Center (0.5 = base) line
    ctx.strokeStyle = 'rgba(255,255,255,0.07)';
    ctx.beginPath(); ctx.moveTo(0, toY(0.5)); ctx.lineTo(W, toY(0.5)); ctx.stroke();

    // Label boundaries when clipping
    if (hasClip) {
      ctx.fillStyle = 'rgba(255,255,255,0.25)';
      ctx.font = '8px sans-serif';
      ctx.textAlign = 'left';
      if (clipsTop) ctx.fillText('100%', 3, toY(1) - 2);
      if (clipsBot) ctx.fillText('0%',   3, toY(0) + 9);
    }

    // Compute points
    const cycleDuration = 60 / (params.rate || 60);
    const pts = Array.from({ length: W + 1 }, (_, x) => {
      const t = (x / W) * cycleDuration;
      return { x, raw: computeEffect(params.table, t, params) };
    });

    // Draw wave — blue in range, red when clipping
    for (let i = 0; i < pts.length - 1; i++) {
      const { x, raw } = pts[i];
      const next = pts[i + 1];
      const clipping = raw > 1 || raw < 0;
      ctx.strokeStyle = clipping ? 'rgba(239,68,68,0.85)' : '#60a5fa';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, toY(raw));
      ctx.lineTo(next.x, toY(next.raw));
      ctx.stroke();
    }

    // "CLIP" badge
    if (hasClip) {
      ctx.fillStyle = 'rgba(239,68,68,0.85)';
      ctx.font = 'bold 8px sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText('CLIP', W - 3, 9);
    }
  }, [params]);

  return <canvas ref={canvasRef} width={220} height={68} className="w-full rounded" />;
}

function NumInput({ label, value, min, max, step = 1, disabled, onChange, placeholder }) {
  return (
    <div className="flex flex-col gap-0.5">
      <label className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</label>
      <input
        type="number"
        min={min} max={max} step={step}
        value={value ?? ''}
        disabled={disabled}
        placeholder={placeholder}
        onChange={e => onChange(e.target.value === '' ? null : Number(e.target.value))}
        className="w-full px-2 py-1 bg-gray-800 border border-gray-700 rounded text-white text-xs focus:border-blue-500 focus:outline-none disabled:opacity-30"
      />
    </div>
  );
}

export default function EffectAttributePanel({
  selectedCells, fixtures, defaultBases, onUpdateCells, onUpdateBase, onClearCells,
  onApplySpread, spread, onSpreadChange,
}) {
  const firstCell = [...selectedCells][0];
  let currentParam = null;
  let currentBase = null;
  if (firstCell) {
    const [fi, pk] = firstCell.split(':');
    const fix = fixtures[parseInt(fi)];
    currentParam = fix?.params[pk] || null;
    currentBase = Math.round((fix?.bases?.[pk] ?? defaultBases?.[pk] ?? 1.0) * 100);
  }

  const hasSelection = selectedCells.size > 0;
  const val = (field, def) => currentParam?.[field] ?? def;

  // Swing range — unclipped raw bounds + clamped actual bounds
  const rangeInfo = (() => {
    if (currentBase === null || !currentParam?.table) return null;
    const base = currentBase / 100;
    const halfRange = (val('size', 50) / 100) / 2;
    const rawLow  = base - halfRange;
    const rawHigh = base + halfRange;
    const low  = Math.round(Math.max(0, rawLow)  * 100);
    const high = Math.round(Math.min(1, rawHigh) * 100);
    const clipsLow  = rawLow  < 0;
    const clipsHigh = rawHigh > 1;
    return { low, high, base: currentBase, clipsLow, clipsHigh };
  })();

  const lengthPct = val('length', 100);

  return (
    <div className="bg-gray-900 border-t border-gray-700 px-4 py-3 flex-shrink-0">
      <div className="flex gap-5 items-start flex-wrap">

        {/* Wave table picker */}
        <div className="flex-shrink-0">
          <div className="text-[10px] text-gray-500 uppercase tracking-wide mb-1.5">Wave Table</div>
          <div className="grid grid-cols-4 gap-1 w-64">
            {TABLES.map(t => (
              <button
                key={t.id}
                disabled={!hasSelection}
                onClick={() => onUpdateCells('table', t.id)}
                className={`px-1.5 py-1 text-[10px] rounded transition-colors font-medium ${
                  currentParam?.table === t.id
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-30 disabled:cursor-not-allowed'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Parameters */}
        <div className="grid grid-cols-3 gap-2 flex-shrink-0 w-52">
          <NumInput label="Base (%)" value={currentBase ?? 100} min={0} max={100} disabled={!hasSelection}
            onChange={v => onUpdateBase(v ?? 100)} />
          <NumInput label="Rate (CPM)" value={val('rate', 60)} min={1} max={600} disabled={!hasSelection}
            onChange={v => onUpdateCells('rate', v ?? 60)} />
          <NumInput label="Size (%)" value={val('size', 50)} min={0} max={400} disabled={!hasSelection}
            onChange={v => onUpdateCells('size', v ?? 50)} />
          <NumInput label="Offset (°)" value={val('offset', 0)} min={0} max={359} disabled={!hasSelection}
            onChange={v => onUpdateCells('offset', v ?? 0)} />
          <NumInput label="Length (%)" value={lengthPct} min={1} max={100} disabled={!hasSelection}
            onChange={v => onUpdateCells('length', v ?? 100)} />
          <NumInput label="N-Shot" value={val('nShot', null)} min={0} placeholder="∞" disabled={!hasSelection}
            onChange={v => onUpdateCells('nShot', v)} />
          <div className="flex flex-col gap-1 col-span-1">
            <div className="text-[10px] text-gray-500 uppercase tracking-wide">Modifiers</div>
            <button
              disabled={!hasSelection}
              onClick={() => onUpdateCells('bounce', !val('bounce', false))}
              className={`px-2 py-1 text-[10px] rounded font-medium transition-colors ${
                val('bounce', false) ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
              } disabled:opacity-30`}
            >
              {val('bounce', false) ? 'Bounce ON' : 'Bounce'}
            </button>
            <button
              disabled={!hasSelection}
              onClick={() => onUpdateCells('direction', val('direction', 'forward') === 'forward' ? 'reverse' : 'forward')}
              className={`px-2 py-1 text-[10px] rounded font-medium transition-colors ${
                val('direction', 'forward') === 'reverse' ? 'bg-orange-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
              } disabled:opacity-30`}
            >
              {val('direction', 'forward') === 'forward' ? 'Forward' : 'Reverse'}
            </button>
          </div>
        </div>

        {/* Spread */}
        <div className="flex flex-col gap-1.5 flex-shrink-0 w-36">
          <div className="text-[10px] text-gray-500 uppercase tracking-wide">Spread</div>
          <input
            type="range" min="0" max="360" step="1"
            value={spread}
            onChange={e => onSpreadChange(Number(e.target.value))}
            className="w-full accent-purple-500"
          />
          <div className="flex justify-between text-[10px] text-gray-500">
            <span>0°</span>
            <span className="text-purple-300 font-mono">{spread}°</span>
            <span>360°</span>
          </div>
          <button
            disabled={!hasSelection}
            onClick={onApplySpread}
            className="px-2 py-1.5 text-[10px] bg-purple-700 hover:bg-purple-600 rounded text-white font-medium disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Apply Spread
          </button>
        </div>

        {/* Waveform preview + swing + length + learn */}
        <div className="flex flex-col gap-1 flex-shrink-0 w-56">
          <div className="text-[10px] text-gray-500 uppercase tracking-wide">Preview</div>
          <WavePreview params={currentParam} />

          {/* Swing range bar */}
          {rangeInfo ? (
            <div className="mt-0.5">
              <div className="flex justify-between text-[10px] mb-0.5">
                <span className={`font-mono ${rangeInfo.clipsLow ? 'text-red-400' : 'text-blue-300'}`}>
                  {rangeInfo.low}%{rangeInfo.clipsLow ? ' ⚠' : ''}
                </span>
                <span className="text-gray-600 text-[9px]">swing</span>
                <span className={`font-mono ${rangeInfo.clipsHigh ? 'text-red-400' : 'text-blue-300'}`}>
                  {rangeInfo.clipsHigh ? '⚠ ' : ''}{rangeInfo.high}%
                </span>
              </div>
              <div className="relative w-full h-2.5 bg-gray-800 rounded overflow-hidden">
                {/* Swing range fill */}
                <div
                  className="absolute top-0 h-full bg-blue-600/50 rounded"
                  style={{ left: `${rangeInfo.low}%`, width: `${rangeInfo.high - rangeInfo.low}%` }}
                />
                {/* Clip indicators */}
                {rangeInfo.clipsLow  && <div className="absolute top-0 left-0 h-full w-1 bg-red-500" />}
                {rangeInfo.clipsHigh && <div className="absolute top-0 right-0 h-full w-1 bg-red-500" />}
                {/* Base tick */}
                <div className="absolute top-0 w-px h-full bg-yellow-400" style={{ left: `${rangeInfo.base}%` }} />
              </div>
              <div className="text-[9px] text-gray-600 text-center mt-0.5">
                base <span className="text-yellow-600">{rangeInfo.base}%</span>
                {' '}— low {rangeInfo.low}% — high {rangeInfo.high}%
                {(rangeInfo.clipsLow || rangeInfo.clipsHigh) && (
                  <span className="text-red-500 ml-1">clips!</span>
                )}
              </div>
            </div>
          ) : (
            <div className="mt-0.5 text-[9px] text-gray-700 text-center">
              {hasSelection ? 'assign an effect to see swing' : 'select a cell'}
            </div>
          )}

          {/* Length duty-cycle bar */}
          {currentParam?.table && (
            <div className="mt-1">
              <div className="flex justify-between text-[10px] mb-0.5">
                <span className="text-gray-500 uppercase tracking-wide text-[9px]">Length</span>
                <span className="text-gray-400 font-mono text-[9px]">{lengthPct}% active</span>
              </div>
              <div className="relative w-full h-2.5 rounded overflow-hidden bg-gray-800 flex">
                <div
                  className="h-full bg-green-600/70 transition-all"
                  style={{ width: `${lengthPct}%` }}
                />
                <div
                  className="h-full bg-gray-600/30"
                  style={{ width: `${100 - lengthPct}%` }}
                />
                {/* Divider tick */}
                {lengthPct < 100 && (
                  <div className="absolute top-0 w-px h-full bg-gray-400/60" style={{ left: `${lengthPct}%` }} />
                )}
              </div>
              <div className="flex justify-between text-[9px] mt-0.5 text-gray-600">
                <span className="text-green-700">effect runs</span>
                {lengthPct < 100 && <span>holds at base</span>}
              </div>
            </div>
          )}

          {/* ── Educational section ── */}
          {currentParam?.table && (() => {
            const size   = val('size',   50);
            const rate   = val('rate',   60);
            const offset = val('offset', 0);
            const length = val('length', 100);
            const bounce = val('bounce', false);
            const secsPerCycle = (60 / rate).toFixed(1);
            const halfSize = (size / 2).toFixed(0);
            const info = TABLE_INFO[currentParam.table];

            const tips = [
              bounce && 'Bounce mirrors the wave — the effect reverses at the end of each cycle instead of resetting.',
              length < 70 && length !== 100 && `Length ${length}%: wave fires for ${(secsPerCycle * length / 100).toFixed(1)}s then holds at base for the rest of the cycle.`,
              size > 100 && 'Size >100%: the output exceeds 0–100% range and clips — creates flat-topped peaks.',
              rate <= 10 && `Very slow (${rate} CPM = ${secsPerCycle}s/cycle) — long, sweeping motion.`,
              rate >= 150 && `Very fast (${rate} CPM = ${secsPerCycle}s/cycle) — rapid flicker or strobe territory.`,
              (offset === 90 || offset === 270) && '90° offset from a perpendicular axis (e.g. tilt) creates circular beam motion.',
            ].filter(Boolean);

            return (
              <div className="mt-1 space-y-1">
                {/* Formula */}
                <div className="bg-gray-900 border border-gray-800 rounded px-2 py-1 font-mono text-[8px] leading-relaxed">
                  <div>
                    <span className="text-gray-500">out =</span>{' '}
                    <span className="text-yellow-500">base</span>{' '}
                    <span className="text-gray-500">±</span>{' '}
                    <span className="text-blue-400">{currentParam.table}</span>
                    <span className="text-gray-500">(t) ×</span>{' '}
                    <span className="text-green-400">{halfSize}%</span>
                  </div>
                  <div className="text-gray-600">t = (sec × {rate}/60 + {offset}/360) mod 1</div>
                </div>

                {/* Table description */}
                {info && (
                  <div className="bg-indigo-950/40 border border-indigo-900/30 rounded px-2 py-1 text-[9px] leading-relaxed">
                    <div className="text-indigo-200">{info.desc}</div>
                    <div className="text-indigo-500/80 mt-0.5">→ {info.use}</div>
                  </div>
                )}

                {/* Contextual tips */}
                {tips.length > 0 && (
                  <div className="space-y-0.5">
                    {tips.map((tip, i) => (
                      <div key={i} className="flex gap-1 items-start text-[9px] text-purple-300/80">
                        <span className="text-purple-500 flex-shrink-0 mt-px">✦</span>
                        <span>{tip}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })()}
        </div>

        {/* Actions */}
        <div className="ml-auto flex flex-col gap-2 flex-shrink-0 self-center">
          <button
            disabled={!hasSelection}
            onClick={onClearCells}
            className="px-4 py-1.5 text-xs bg-red-900 hover:bg-red-800 rounded text-white font-medium disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Clear Effect
          </button>
          <div className="text-[10px] text-gray-600 text-center">
            {selectedCells.size} cell{selectedCells.size !== 1 ? 's' : ''} selected
          </div>
        </div>
      </div>
    </div>
  );
}
