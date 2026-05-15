// ─────────── Basic wave generators ───────────
export function sineWave(t) {
  return Math.sin(2 * Math.PI * t);
}
export function sawtoothWave(t) {
  return 2 * (t - Math.floor(t + 0.5));
}
export function stepWave(t) {
  return t % 1 < 0.5 ? 1 : -1;
}

// ─────────── Hog4-style tangent curve ───────────
export function tangentWave(t) {
  const raw = Math.tan((t - 0.5) * Math.PI);
  const clamped = Math.max(-4, Math.min(4, raw));
  return clamped / 4;
}

// ─────────── Spiral (double-tangent) ───────────
export function spiralWave(t) {
  if (t < 0.5) return tangentWave(t * 2);
  return tangentWave((1 - t) * 2);
}

// ─────────── Random tables ───────────
const _randomState = {
  random1: { cycle: -1, val: 0 },
  random2: { cycle: -1, val: 0 },
  random3: { cycle: -1, val: 0 },
};
function getRandomFor(table, cycleIndex) {
  const state = _randomState[table];
  if (state.cycle !== cycleIndex) {
    state.cycle = cycleIndex;
    if (table === 'random1') {
      // Low-weighted: biased toward values below base (toward -1)
      state.val = -(Math.random() ** 0.5);
    } else if (table === 'random2') {
      // High-weighted: biased toward values above base (toward +1)
      state.val = Math.random() ** 0.5;
    } else if (table === 'random3') {
      // Center-weighted: clustered near base — subtle variation
      const r1 = Math.random(), r2 = Math.random();
      state.val = ((r1 + r2) / 2) * 2 - 1;
    }
  }
  return state.val;
}

// ─────────── Main computeEffect ───────────
/**
 * table:     'sine','tangent','sawtooth','ramp','inverseRamp',
 *            'step','markOn','markOff','spiral','random1','random2','random3'
 * params:    { rate, size, offset, length, bounce, direction, nShot }
 * returns:   [0…1] value centered at 0.5
 */
export function computeEffect(table, timeSec, params) {
  const { rate, size, offset, length, bounce, direction, nShot } = params;
  const cyclesPerSec = (rate || 60) / 60;
  const totalCycles = timeSec * cyclesPerSec;

  // n-shot: freeze at center value after nShot cycles
  if (nShot != null && nShot > 0 && totalCycles >= nShot) return 0.5;

  // 1) phase in [0,1)
  let phase = (totalCycles + (offset || 0) / 360) % 1;
  if (phase < 0) phase += 1;
  if (bounce && phase > 0.5) phase = 1 - phase;
  if (direction === 'reverse') phase = 1 - phase;

  // Length gate: waveform is active for the first (length)% of the cycle,
  // then holds at base (0.5) for the remainder — Hog-accurate duty-cycle behavior.
  const activePortion = (length == null ? 100 : length) / 100;
  if (activePortion < 1 && phase >= activePortion) return 0.5;

  // 2) pick base wave in [-1…1]
  // markOn/markOff are pure +1/-1 pulses; the length gate above handles duty-cycle.
  let wave;
  switch (table) {
    case 'sine':        wave = sineWave(phase);    break;
    case 'tangent':     wave = tangentWave(phase); break;
    case 'sawtooth':    wave = sawtoothWave(phase); break;
    case 'ramp':        wave = 2 * phase - 1;      break;
    case 'inverseRamp': wave = 1 - 2 * phase;      break;
    case 'step':        wave = stepWave(phase);    break;
    case 'markOn':      wave = 1;                  break;
    case 'markOff':     wave = -1;                 break;
    case 'spiral':      wave = spiralWave(phase);  break;
    case 'random1':
    case 'random2':
    case 'random3': {
      const cycleIndex = Math.floor(totalCycles);
      wave = getRandomFor(table, cycleIndex);
      break;
    }
    default: wave = sineWave(phase);
  }

  // 3) size scaling: size% → full swing span, centered at 0.5.
  // Size > 100% is valid — output will exceed [0,1] and clip at the caller.
  const halfRange = ((size || 50) / 100) / 2;
  return 0.5 + wave * halfRange;
}
