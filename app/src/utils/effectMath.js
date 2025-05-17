// File: src/utils/effectMath.js

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
  // Steep S-curve: tan((t–0.5)*π) clamped to [-1…1]
  export function tangentWave(t) {
    const raw = Math.tan((t - 0.5) * Math.PI);
    const clamped = Math.max(-4, Math.min(4, raw));
    return clamped / 4;
  }
  
  // ─────────── Spiral (double-tangent) ───────────
  export function spiralWave(t) {
    // two mirrored tangent lobes per cycle
    if (t < 0.5) return tangentWave(t * 2);
    return tangentWave((1 - t) * 2);
  }
  
  // ─────────── Random tables ───────────
  // We store one random value per cycle so it doesn't jitter each frame.
  const _randomState = {
    random1: { cycle: -1, val: 0 },
    random2: { cycle: -1, val: 0 },
    random3: { cycle: -1, val: 0 },
  };
  function getRandomFor(table, cycleIndex) {
    const state = _randomState[table];
    if (state.cycle !== cycleIndex) {
      state.cycle = cycleIndex;
      // uniform noise
      if (table === 'random1') {
        state.val = Math.random() * 2 - 1;
      }
      // high-weighted → more extreme: sqrt distribution
      else if (table === 'random2') {
        const r = Math.random();
        state.val = (Math.random() < 0.5 ? -1 : 1) * Math.sqrt(r);
      }
      // center-weighted → average of two → cluster around 0
      else if (table === 'random3') {
        const r1 = Math.random(), r2 = Math.random();
        state.val = ((r1 + r2) / 2) * 2 - 1;
      }
    }
    return state.val;
  }
  
  // ─────────── Main computeEffect ───────────
  /**
   * table:     'sine','tangent','sawtooth','ramp','inverseRamp',
   *            'step','markOn','markOff','spiral',
   *            'random1','random2','random3'
   * params:    { rate, size, offset, length, bounce, direction }
   * returns:   [0…1] value, with size% → full peak-to-peak span
   */
  export function computeEffect(table, timeSec, params) {
    const { rate, size, offset, length, bounce, direction } = params;
  
    // 1) phase in [0,1)
    const cyclesPerSec = rate / 60;
    let phase = (timeSec * cyclesPerSec + offset / 360) % 1;
    if (bounce && phase > 0.5) phase = 1 - phase;
    if (direction === 'reverse') phase = 1 - phase;
  
    // 2) pick base wave in [-1…1]
    let wave;
    switch (table) {
      case 'sine':        wave = sineWave(phase);       break;
      case 'tangent':     wave = tangentWave(phase);    break;
      case 'sawtooth':    wave = sawtoothWave(phase);   break;
      case 'ramp':        wave = 2 * phase - 1;         break; // linear up
      case 'inverseRamp': wave = 1 - 2 * phase;         break; // linear down
      case 'step':        wave = stepWave(phase);       break;
      case 'markOn':      wave = phase < (length/100) ? 1 : -1; break;
      case 'markOff':     wave = phase < (length/100) ? -1 : 1; break;
      case 'spiral':      wave = spiralWave(phase);     break;
      case 'random1':
      case 'random2':
      case 'random3':
        const cycleIndex = Math.floor(timeSec * cyclesPerSec);
        wave = getRandomFor(table, cycleIndex);
        break;
      default:            wave = sineWave(phase);
    }
  
    // 3) size scaling: size% → full swing span, centered at 0.5
    //    halfRange = (size/100)/2
    const halfRange = (size / 100) / 2;
    const value = 0.5 + wave * halfRange;
  
    // 4) duty-cycle length: zero out after length%
    const active = phase < (length / 100);
    return active ? value : 0;
  }
  