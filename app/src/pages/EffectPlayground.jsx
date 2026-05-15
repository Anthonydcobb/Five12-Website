import React, { useState, useRef, useEffect, useCallback } from 'react';
import EffectsGrid from '../components/EffectsGrid';
import EffectAttributePanel from '../components/EffectAttributePanel';
import FixtureVisualizer from '../components/FixtureVisualizer';

const PARAM_KEYS = ['intensity', 'pan', 'tilt', 'red', 'green', 'blue'];

const DEFAULT_PARAM = {
  table: null, rate: 60, size: 50, offset: 0,
  length: 100, bounce: false, direction: 'forward', nShot: null,
};

const DEFAULT_BASES = { intensity: 1.0, pan: 0.5, tilt: 0.5, red: 1.0, green: 1.0, blue: 1.0 };

const PALETTES = [
  {
    name: 'Circle',
    desc: 'Sine pan+tilt 90° offset',
    why: 'Sine on pan = left/right oscillation. Sine on tilt 90° out of phase = up/down oscillation, but a quarter-cycle behind. Two perpendicular sine waves 90° apart trace a perfect circle — the same math as a unit circle where X=cos(t) and Y=sin(t).',
    params: {
      pan:  { table: 'sine', rate: 30, size: 60, offset: 0 },
      tilt: { table: 'sine', rate: 30, size: 60, offset: 90 },
    },
  },
  {
    name: 'Square',
    desc: 'Sawtooth pan+tilt 90° offset',
    why: 'Sawtooth ramps linearly in one direction then snaps back. Same 90° offset trick as Circle, but the linear ramp creates straight edges instead of a curve — so the path is a square instead of a circle.',
    params: {
      pan:  { table: 'sawtooth', rate: 30, size: 60, offset: 0 },
      tilt: { table: 'sawtooth', rate: 30, size: 60, offset: 90 },
    },
  },
  {
    name: 'Figure 8',
    desc: 'Sine pan + half-rate sine tilt',
    why: 'Pan runs at 30 CPM; tilt runs at 15 CPM — exactly half the rate. For every one full tilt cycle, pan completes two full cycles. That 2:1 ratio creates the classic figure-8 (Lissajous curve). Change the ratio to 3:1 for a trefoil shape.',
    params: {
      pan:  { table: 'sine', rate: 30, size: 60, offset: 0 },
      tilt: { table: 'sine', rate: 15, size: 40, offset: 0 },
    },
  },
  {
    name: 'Can-Can',
    desc: 'Step pan + sine tilt',
    why: 'Step on pan hard-cuts between left and right positions with no transition. Meanwhile, sine on tilt is kicking up and down smoothly. The combination looks like a chorus line — fixtures snapping side to side while continuously bobbing.',
    params: {
      pan:  { table: 'step', rate: 30, size: 40, offset: 0 },
      tilt: { table: 'sine', rate: 60, size: 50, offset: 0 },
    },
  },
  {
    name: 'Ripple',
    desc: 'Sine intensity with spread',
    why: 'Sine intensity with 360° spread applied across fixtures means each fixture is at a different point in the same wave — like watching a wave travel across water. The spread is the key: without it, all fixtures pulse together.',
    params: {
      intensity: { table: 'sine', rate: 40, size: 70, offset: 0 },
    },
  },
  {
    name: 'Color Chase',
    desc: 'RGB sine 120° apart',
    why: 'Three sine waves, each 120° apart, cover a full 360° cycle. When one color peaks, the others are 1/3 and 2/3 of the way through their cycle. This creates smooth, continuous color rotation — no channel ever goes dark at the same time.',
    params: {
      red:   { table: 'sine', rate: 40, size: 80, offset: 0 },
      green: { table: 'sine', rate: 40, size: 80, offset: 120 },
      blue:  { table: 'sine', rate: 40, size: 80, offset: 240 },
    },
  },
  {
    name: 'Fly In',
    desc: 'Step pan + ramp tilt',
    why: 'Step snaps pan between two positions, while ramp linearly sweeps tilt from low to high over the same period. The hard snap + linear climb creates a "fly in from the side" look — the light appears to arrive from off-stage.',
    params: {
      pan:  { table: 'step', rate: 20, size: 60, offset: 0 },
      tilt: { table: 'ramp', rate: 20, size: 60, offset: 0 },
    },
  },
  {
    name: 'Iris Chase',
    desc: 'Sawtooth intensity',
    why: 'Sawtooth ramps intensity from low to high, then snaps back instantly. With spread across fixtures, each one is at a different point in that ramp — creating a directional "wave" effect. The hard snap gives it a chaser rather than a ripple feel.',
    params: {
      intensity: { table: 'sawtooth', rate: 60, size: 80, offset: 0 },
    },
  },
  {
    name: 'Tangent Snap',
    desc: 'Tangent pan + sine tilt',
    why: 'Tangent spends most of its time near center, then accelerates extremely fast near the extremes — a "crack the whip" shape. Paired with smooth sine on tilt, the beam lingers in the center zone then snaps to one side while tilt carries it up or down.',
    params: {
      pan:  { table: 'tangent', rate: 30, size: 50, offset: 0 },
      tilt: { table: 'sine',    rate: 30, size: 40, offset: 45 },
    },
  },
  {
    name: 'Breathe',
    desc: 'Slow sine intensity — organic pulse',
    why: 'A very slow sine on intensity creates the feeling of breathing. Sine\'s smooth acceleration at the peaks (it slows down as it approaches 100% and 0%) makes it feel alive, unlike a ramp which would feel mechanical.',
    params: {
      intensity: { table: 'sine', rate: 18, size: 70, offset: 0 },
    },
  },
  {
    name: 'Pendulum',
    desc: 'Sine pan only — side-to-side swing',
    why: 'Pure sine on pan with no tilt effect. Sine naturally decelerates at the extremes and accelerates through center — exactly like a real pendulum. Try adding Bounce to make it reverse instead of loop.',
    params: {
      pan: { table: 'sine', rate: 22, size: 65, offset: 0 },
    },
  },
  {
    name: 'Star Field',
    desc: 'High-biased random intensity + subtle color drift',
    why: 'Rnd High biases values toward the top of the range — each fixture stays mostly bright with occasional extra-bright hits, like stars. Adding slow Rnd Mid on R and B channels gives each "star" a slightly different color temperature.',
    params: {
      intensity: { table: 'random2', rate: 25, size: 60, offset: 0 },
      red:       { table: 'random3', rate: 15, size: 25, offset: 0 },
      blue:      { table: 'random3', rate: 18, size: 25, offset: 0 },
    },
  },
  {
    name: 'Color Wash',
    desc: 'Slow random drift per RGB channel',
    why: 'Center-weighted random (Rnd Mid) on each RGB channel at slightly different rates means the color evolves slowly and never repeats exactly. Three channels at co-prime rates (8, 11, 13 CPM) cycle together only every ~96 minutes.',
    params: {
      red:   { table: 'random3', rate: 8,  size: 70, offset: 0 },
      green: { table: 'random3', rate: 11, size: 70, offset: 0 },
      blue:  { table: 'random3', rate: 13, size: 70, offset: 0 },
    },
  },
  {
    name: 'Slow Wave',
    desc: 'Very slow sine intensity — rolling ocean',
    why: 'At 6 CPM (10-second cycles) with high spread across fixtures, the sine wave moves across the rig like a slow ocean swell. Slow rate + high spread = you can see the entire wave shape across your fixtures at once.',
    params: {
      intensity: { table: 'sine', rate: 6, size: 85, offset: 0 },
    },
  },
  {
    name: 'Strobe Pulse',
    desc: 'Mark On with short length — beat hit',
    why: 'Mark On holds at full intensity for exactly Length% of each cycle, then instantly returns to base. With Length at 15%, the fixture fires a quick bright hit and then rests — like a strobe on a beat. Rate controls BPM.',
    params: {
      intensity: { table: 'markOn', rate: 60, size: 100, offset: 0, length: 15 },
    },
  },
];

function makeFixture(id, index = 0) {
  const cols = 3;
  const col  = index % cols;
  const row  = Math.floor(index / cols);
  // Spread fixtures across the stage in a grid: columns at 20/50/80%, rows down
  const pan  = cols > 1 ? 0.20 + (col / (cols - 1)) * 0.60 : 0.5;
  const tilt = 0.20 + row * 0.28;
  const params = {};
  PARAM_KEYS.forEach(pk => { params[pk] = null; });
  return {
    id,
    params,
    bases: { ...DEFAULT_BASES, pan: Math.min(0.85, pan), tilt: Math.min(0.85, tilt) },
  };
}

function applyPaletteDefaults(paletteParams, fixtureIndex, numFixtures, spreadDeg) {
  const result = {};
  Object.entries(paletteParams).forEach(([pk, overrides]) => {
    const spreadOffset = numFixtures > 1 ? (fixtureIndex / numFixtures) * spreadDeg : 0;
    result[pk] = {
      ...DEFAULT_PARAM,
      ...overrides,
      offset: (overrides.offset || 0) + spreadOffset,
    };
  });
  return result;
}

export default function EffectPlayground() {
  const [fixtures, setFixtures] = useState(() =>
    Array.from({ length: 6 }, (_, i) => makeFixture(i + 1, i))
  );
  const [selectedCells, setSelectedCells] = useState(new Set());
  const [masterRate, setMasterRate] = useState(1.0);
  const [spread, setSpread] = useState(0);
  const [hoveredPalette, setHoveredPalette] = useState(null);

  const timeRef = useRef(0);
  const startRef = useRef(null);

  // Master clock — drives FixtureVisualizer canvas via ref (no React state updates)
  useEffect(() => {
    let rafId;
    const tick = (now) => {
      if (!startRef.current) startRef.current = now;
      timeRef.current = (now - startRef.current) / 1000;
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, []);

  const handleCellClick = useCallback((fi, pk, e) => {
    const key = `${fi}:${pk}`;
    setSelectedCells(prev => {
      const next = new Set(prev);
      if (e.ctrlKey || e.metaKey) {
        if (next.has(key)) next.delete(key); else next.add(key);
      } else {
        if (next.size === 1 && next.has(key)) {
          next.clear();
        } else {
          next.clear();
          next.add(key);
        }
      }
      return next;
    });
  }, []);

  const handleUpdateCells = useCallback((field, value) => {
    setFixtures(prev => prev.map((fix, fi) => {
      let changed = false;
      const updatedParams = { ...fix.params };
      PARAM_KEYS.forEach(pk => {
        if (selectedCells.has(`${fi}:${pk}`)) {
          const existing = updatedParams[pk] || { ...DEFAULT_PARAM };
          updatedParams[pk] = { ...existing, [field]: value };
          changed = true;
        }
      });
      return changed ? { ...fix, params: updatedParams } : fix;
    }));
  }, [selectedCells]);

  const handleClearCells = useCallback(() => {
    setFixtures(prev => prev.map((fix, fi) => {
      let changed = false;
      const updatedParams = { ...fix.params };
      PARAM_KEYS.forEach(pk => {
        if (selectedCells.has(`${fi}:${pk}`)) {
          updatedParams[pk] = null;
          changed = true;
        }
      });
      return changed ? { ...fix, params: updatedParams } : fix;
    }));
  }, [selectedCells]);

  const handleUpdateBase = useCallback((pct) => {
    const value = Math.max(0, Math.min(1, pct / 100));
    setFixtures(prev => prev.map((fix, fi) => {
      let changed = false;
      const updatedBases = { ...fix.bases };
      PARAM_KEYS.forEach(pk => {
        if (selectedCells.has(`${fi}:${pk}`)) {
          updatedBases[pk] = value;
          changed = true;
        }
      });
      return changed ? { ...fix, bases: updatedBases } : fix;
    }));
  }, [selectedCells]);

  const handleApplySpread = useCallback(() => {
    const fiIndices = new Set();
    selectedCells.forEach(key => fiIndices.add(parseInt(key.split(':')[0])));
    const sortedFi = [...fiIndices].sort((a, b) => a - b);
    const N = sortedFi.length;
    if (N < 2) return;

    setFixtures(prev => {
      const next = [...prev];
      sortedFi.forEach((fi, idx) => {
        const fixtureSpreadOffset = (idx / N) * spread;
        const updatedParams = { ...next[fi].params };
        PARAM_KEYS.forEach(pk => {
          if (selectedCells.has(`${fi}:${pk}`) && updatedParams[pk]?.table) {
            updatedParams[pk] = { ...updatedParams[pk], offset: fixtureSpreadOffset };
          }
        });
        next[fi] = { ...next[fi], params: updatedParams };
      });
      return next;
    });
  }, [selectedCells, spread]);

  const applyPalette = useCallback((palette) => {
    const N = fixtures.length;
    setFixtures(prev => prev.map((fix, fi) => ({
      ...fix,
      params: {
        ...fix.params,
        ...applyPaletteDefaults(palette.params, fi, N, spread),
      },
    })));
    setSelectedCells(new Set());
  }, [fixtures.length, spread]);

  const handleUpdateFixtureBase = useCallback((fixtureId, pan, tilt) => {
    setFixtures(prev => prev.map(fix =>
      fix.id === fixtureId
        ? { ...fix, bases: { ...fix.bases, pan, tilt } }
        : fix
    ));
  }, []);

  const addFixture = () => setFixtures(prev => {
    const maxId = Math.max(...prev.map(f => f.id), 0);
    return [...prev, makeFixture(maxId + 1, prev.length)];
  });

  const removeFixture = () => {
    if (fixtures.length <= 1) return;
    setFixtures(prev => prev.slice(0, -1));
    setSelectedCells(new Set());
  };

  const clearAll = () => {
    setFixtures(prev => prev.map(fix => ({
      ...fix,
      params: Object.fromEntries(PARAM_KEYS.map(pk => [pk, null])),
      bases: { ...DEFAULT_BASES },
    })));
    setSelectedCells(new Set());
  };

  const resetTime = () => { startRef.current = null; };

  return (
    <div className="flex flex-col bg-gray-900 text-white" style={{ height: 'calc(100vh - 48px)' }}>

      {/* Top bar */}
      <div className="flex items-center gap-4 px-4 py-2 bg-gray-800 border-b border-gray-700 flex-shrink-0">
        <h1 className="text-sm font-bold tracking-widest text-blue-400 uppercase">Effects Engine</h1>

        <div className="flex items-center gap-2 ml-4">
          <span className="text-[11px] text-gray-400 uppercase tracking-wide">Master Rate</span>
          <input
            type="range" min="0.1" max="4" step="0.05"
            value={masterRate}
            onChange={e => setMasterRate(parseFloat(e.target.value))}
            className="w-28 accent-blue-500"
          />
          <span className="text-xs font-mono text-white w-10">{masterRate.toFixed(2)}×</span>
        </div>

        <div className="flex items-center gap-1">
          <button onClick={addFixture} className="px-2 py-1 text-[11px] bg-gray-700 hover:bg-gray-600 rounded text-green-400 font-medium">+ Fix</button>
          <button onClick={removeFixture} disabled={fixtures.length <= 1} className="px-2 py-1 text-[11px] bg-gray-700 hover:bg-gray-600 rounded text-red-400 font-medium disabled:opacity-30">− Fix</button>
          <span className="text-[11px] text-gray-500 font-mono ml-1">{fixtures.length} fixtures</span>
        </div>

        <button onClick={resetTime} className="px-3 py-1 text-[11px] bg-gray-700 hover:bg-gray-600 rounded text-yellow-400">Reset Clock</button>
        <button onClick={clearAll} className="ml-auto px-3 py-1 text-[11px] bg-red-900 hover:bg-red-800 rounded text-white font-medium">Clear All</button>
      </div>

      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">

        {/* Left: Palettes */}
        <aside className="w-44 bg-gray-800 border-r border-gray-700 flex flex-col flex-shrink-0">
          <div className="text-[10px] text-gray-500 uppercase tracking-widest px-3 py-2 border-b border-gray-700 flex-shrink-0">Palettes</div>
          <div className="flex-1 overflow-y-auto">
            {PALETTES.map(p => (
              <button
                key={p.name}
                onClick={() => applyPalette(p)}
                onMouseEnter={() => setHoveredPalette(p)}
                onMouseLeave={() => setHoveredPalette(null)}
                className="w-full text-left px-3 py-2 text-xs bg-transparent hover:bg-gray-700 text-gray-200 border-b border-gray-700/50 transition-colors"
              >
                <div className="font-medium">{p.name}</div>
                <div className="text-[10px] text-gray-500 leading-tight mt-0.5">{p.desc}</div>
              </button>
            ))}
          </div>
          {/* Why it works — shown on hover */}
          {hoveredPalette?.why && (
            <div className="border-t border-gray-700 px-3 py-2 flex-shrink-0">
              <div className="text-[9px] text-yellow-500 uppercase tracking-wide mb-1">Why it works</div>
              <div className="text-[9px] text-gray-300 leading-relaxed">{hoveredPalette.why}</div>
            </div>
          )}
        </aside>

        {/* Center: Grid */}
        <div className="flex-1 overflow-auto bg-gray-900">
          <EffectsGrid
            fixtures={fixtures}
            selectedCells={selectedCells}
            onCellClick={handleCellClick}
            paramKeys={PARAM_KEYS}
          />
        </div>

        {/* Right: Visualizer */}
        <aside className="w-72 bg-gray-950 border-l border-gray-700 flex flex-col flex-shrink-0">
          <div className="text-[10px] text-gray-500 uppercase tracking-widest px-3 py-2 border-b border-gray-700">Stage View</div>
          <div className="flex-1 p-2 min-h-0">
            <FixtureVisualizer
            fixtures={fixtures}
            timeRef={timeRef}
            masterRate={masterRate}
            onUpdateBase={handleUpdateFixtureBase}
          />
          </div>
          {/* Live values legend */}
          <div className="px-3 py-2 border-t border-gray-800 text-[10px] text-gray-600">
            <div>Pan / Tilt → XY position</div>
            <div>Intensity → size + brightness</div>
            <div>RGB → beam color</div>
          </div>
        </aside>
      </div>

      {/* Bottom: Attribute Panel */}
      <EffectAttributePanel
        selectedCells={selectedCells}
        fixtures={fixtures}
        defaultBases={DEFAULT_BASES}
        onUpdateCells={handleUpdateCells}
        onUpdateBase={handleUpdateBase}
        onClearCells={handleClearCells}
        onApplySpread={handleApplySpread}
        spread={spread}
        onSpreadChange={setSpread}
      />
    </div>
  );
}
