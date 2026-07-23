// Parse a printer-style page-range expression into 0-based positions.
// "2-4, 10-15, 20" over max=N -> [1,2,3, 9,10,11,12,13,14, 19] (each clamped to [1,N]).
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
      for (let n = a; step > 0 ? n <= b : n >= b; n += step) {
        if (n >= 1 && n <= max) out.push(n - 1);
      }
    } else if (/^\d+$/.test(token)) {
      const n = parseInt(token, 10);
      if (n >= 1 && n <= max) out.push(n - 1);
    }
    // else: malformed token -> ignore
  }
  return out;
}
