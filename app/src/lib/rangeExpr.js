// Parse a printer-style page-range expression into 0-based positions.
// "2-4, 10-15, 20" over max=N -> [1,2,3, 9,10,11,12,13,14, 19] (positions outside [1,N] are dropped).
// Order is as-written; duplicates are kept; malformed tokens are ignored.
export function parseRangeExpr(expr, max) {
  if (!max || max < 1) return [];
  const out = [];
  for (const raw of String(expr ?? '').split(',')) {
    const token = raw.trim();
    if (!token) continue;
    const m = token.match(/^(\d+)\s*-\s*(\d+)$/);
    if (m) {
      const a = parseInt(m[1], 10);
      const b = parseInt(m[2], 10);
      const step = a <= b ? 1 : -1;
      // Clamp the range to [1, max] before iterating to avoid iterating huge spans.
      // Preserves direction, duplicates, and order as-written.
      let start, end;
      if (step > 0) {
        start = Math.max(a, 1);
        end = Math.min(b, max);
      } else {
        start = Math.min(a, max);
        end = Math.max(b, 1);
      }
      // Only iterate if the clamped range is valid (no overlap with [1, max]).
      if (step > 0 ? start <= end : start >= end) {
        for (let n = start; step > 0 ? n <= end : n >= end; n += step) {
          out.push(n - 1);
        }
      }
    } else if (/^\d+$/.test(token)) {
      const n = parseInt(token, 10);
      if (n >= 1 && n <= max) out.push(n - 1);
    }
    // else: malformed token -> ignore
  }
  return out;
}
