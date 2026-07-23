# DYMO Print Dialog — preview jog + print scope — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the DYMO print dialog jog through every merged label preview and print an arbitrary subset via a printer-style page-range expression.

**Architecture:** Frontend-only change. Extract the range parser to a pure module (`app/src/lib/rangeExpr.js`) so it can be verified with a Node ESM check, then wire two independent UI additions into `DymoPrintDialog.jsx`: a preview pager (view aid) and an All/Custom print-scope selector that slices the records array actually sent to `printMerge`.

**Tech Stack:** React 19 (hooks), Vite, Tailwind CSS 4. No new dependencies.

## Global Constraints

- Frontend only — no backend, API, or `app/src/lib/dymo.js` / `labelMerge.js` signature changes.
- Preserve existing behavior in "All" mode: mapping table, source selection, CSV parsing, live-render, printer persistence (`five12_dymo_printer`), and mapping-save-after-print (`PUT /api/dymo-templates/:id/mapping`) all unchanged.
- All positions are 1-based in the UI, 0-based internally; `parseRangeExpr` returns 0-based indices to index `records` directly.
- Range expression semantics (verbatim from spec): order = as written; duplicates kept; malformed tokens ignored; each position clamped to `[1, N]` and out-of-range dropped.
- Branch: `feat/dymo-label-merge`. No new frontend test framework — the repo has none; verify the parser via Node, the UI manually.
- Scratchpad for throwaway verification files: `C:\Users\antho\AppData\Local\Temp\claude\C--Users-antho\f471225f-62b6-4f9f-aca7-c151ed957b98\scratchpad` (git-bash: `/c/Users/antho/AppData/Local/Temp/claude/C--Users-antho/f471225f-62b6-4f9f-aca7-c151ed957b98/scratchpad`).

---

### Task 1: `parseRangeExpr` pure helper

**Files:**
- Create: `app/src/lib/rangeExpr.js`
- Verify (throwaway, not committed): scratchpad `rangeExpr.mjs` copy + `check.mjs`

**Interfaces:**
- Produces: `parseRangeExpr(expr: string, max: number) => number[]` — 0-based positions into a `records` array of length `max`. Consumed by Task 3.

- [ ] **Step 1: Write the implementation**

Create `app/src/lib/rangeExpr.js`:

```js
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
```

- [ ] **Step 2: Write the verification check**

The repo has no JS test runner and `.js` files load as CommonJS under Node, so copy the source to a `.mjs` (making Node treat it as ESM) and run assertions against the real file. Create the check in the scratchpad:

Write `<scratchpad>/check.mjs`:

```js
import { parseRangeExpr } from './rangeExpr.mjs';
import assert from 'node:assert';

const eq = (got, exp, msg) =>
  assert.deepStrictEqual(got, exp, `${msg} -> got ${JSON.stringify(got)}`);

// basic single + range, 1-based in -> 0-based out
eq(parseRangeExpr('8', 55), [7], 'single');
eq(parseRangeExpr('2-4', 55), [1, 2, 3], 'range');
// comma of ranges, order as written
eq(parseRangeExpr('2-4, 10-15', 55), [1, 2, 3, 9, 10, 11, 12, 13, 14], 'multi');
eq(parseRangeExpr('10-15, 2-4', 55), [9, 10, 11, 12, 13, 14, 1, 2, 3], 'as-written order');
// duplicates kept
eq(parseRangeExpr('5, 5', 55), [4, 4], 'dupes kept');
// clamp / drop out of range
eq(parseRangeExpr('50-60', 55), [49, 50, 51, 52, 53, 54], 'clamp high');
eq(parseRangeExpr('0-3', 55), [0, 1, 2], 'drop zero');
// reversed token expands in written direction
eq(parseRangeExpr('4-2', 55), [3, 2, 1], 'reversed');
// malformed / empty -> ignored / empty
eq(parseRangeExpr('abc', 55), [], 'malformed');
eq(parseRangeExpr('', 55), [], 'empty');
eq(parseRangeExpr('2-4', 0), [], 'zero max');
eq(parseRangeExpr('  3 , , 7 ', 55), [2, 6], 'whitespace + empty tokens');

console.log('OK — all parseRangeExpr assertions passed');
```

- [ ] **Step 3: Run the verification — expect PASS**

Run (git-bash):

```bash
SCRATCH="/c/Users/antho/AppData/Local/Temp/claude/C--Users-antho/f471225f-62b6-4f9f-aca7-c151ed957b98/scratchpad"
cp "/c/Users/antho/OneDrive/Documents/Five12-TheApp/app/src/lib/rangeExpr.js" "$SCRATCH/rangeExpr.mjs"
node "$SCRATCH/check.mjs"
```

Expected output: `OK — all parseRangeExpr assertions passed` (exit 0). If any assertion throws, fix `rangeExpr.js` and re-run.

- [ ] **Step 4: Commit**

```bash
cd "/c/Users/antho/OneDrive/Documents/Five12-TheApp"
git add app/src/lib/rangeExpr.js
git commit -m "feat(dymo): parseRangeExpr — printer-style page-range parser"
```

---

### Task 2: Preview jog (pager)

**Files:**
- Modify: `app/src/components/DymoPrintDialog.jsx`

**Interfaces:**
- Consumes: existing `records` memo (array), `tpl`, `source`, `csv`, `ready`, `renderPreview`.
- Produces: `previewIndex` state (0-based) driving the live-render effect. Independent of print scope.

- [ ] **Step 1: Add previewIndex state**

After the `preview` state line (`const [preview, setPreview] = useState(null);`, ~line 77) add:

```jsx
  const [previewIndex, setPreviewIndex] = useState(0);
```

- [ ] **Step 2: Reset/clamp previewIndex when the record set changes**

After the `records` memo (ends ~line 110) add two effects:

```jsx
  // jump back to the first label on a structural source/template change
  useEffect(() => { setPreviewIndex(0); }, [tpl, source, csv]);
  // keep the index valid if the record count shrinks (e.g. mapping edit)
  useEffect(() => {
    setPreviewIndex(i => Math.min(i, Math.max(0, records.length - 1)));
  }, [records.length]);
```

- [ ] **Step 3: Render the jogged record instead of records[0]**

Replace the live-preview effect (currently `renderPreview(tpl.labelXml, records[0])`, ~lines 130-137) with:

```jsx
  // live preview of the currently-jogged record
  useEffect(() => {
    if (!tpl || !records.length || ready !== true) { setPreview(null); return; }
    const rec = records[Math.min(previewIndex, records.length - 1)];
    let alive = true;
    renderPreview(tpl.labelXml, rec)
      .then(png => { if (alive) setPreview(png); })
      .catch(() => { if (alive) setPreview(null); });
    return () => { alive = false; };
  }, [tpl, records, previewIndex, ready]);
```

- [ ] **Step 4: Add arrow-key stepping**

After the effects above, add a window keydown listener (skips when typing in a field):

```jsx
  // left/right arrows step the preview, unless focus is in an input/select
  useEffect(() => {
    const max = records.length - 1;
    const onKey = (e) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return;
      if (e.key === 'ArrowLeft') setPreviewIndex(i => Math.max(0, i - 1));
      else if (e.key === 'ArrowRight') setPreviewIndex(i => Math.min(max, i + 1));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [records.length]);
```

- [ ] **Step 5: Add the pager UI under the preview image**

Replace the preview panel block (currently the `<div className="bg-bg border border-border rounded-lg p-3 flex items-center justify-center min-h-[140px]">…</div>`, ~lines 228-233) with:

```jsx
            <div className="flex flex-col gap-2">
              <div className="bg-bg border border-border rounded-lg p-3 flex items-center justify-center min-h-[140px]">
                {preview
                  ? <img alt="label preview" className="max-w-full max-h-[220px]" src={`data:image/png;base64,${preview}`} />
                  : <span className="text-text-muted text-xs">preview appears when mapped</span>}
              </div>
              {records.length > 0 && (
                <div className="flex items-center justify-center gap-2 text-sm text-text-muted">
                  <button type="button" aria-label="previous label"
                    onClick={() => setPreviewIndex(i => Math.max(0, i - 1))}
                    disabled={previewIndex <= 0}
                    className="px-2 py-0.5 rounded border border-border disabled:opacity-30 hover:bg-surface-2">‹</button>
                  <span className="flex items-center gap-1">
                    Label
                    <input type="number" min={1} max={records.length} value={previewIndex + 1}
                      onChange={e => {
                        const n = parseInt(e.target.value, 10);
                        if (!Number.isNaN(n)) setPreviewIndex(Math.min(records.length - 1, Math.max(0, n - 1)));
                      }}
                      className="w-14 bg-bg border border-border rounded px-1 py-0.5 text-center text-text" />
                    of {records.length}
                  </span>
                  <button type="button" aria-label="next label"
                    onClick={() => setPreviewIndex(i => Math.min(records.length - 1, i + 1))}
                    disabled={previewIndex >= records.length - 1}
                    className="px-2 py-0.5 rounded border border-border disabled:opacity-30 hover:bg-surface-2">›</button>
                </div>
              )}
            </div>
```

- [ ] **Step 6: Manual verification in the browser**

Servers are already up (backend :5000, Vite :5173). In the DYMO tab open the print dialog on "LZMU Dymo Label Big" with a multi-row source. Verify:
- Preview shows label 1; `‹`/`›` step through all N; buttons disable at the first/last label.
- Typing a number in the "Label [n]" box jumps to that label (clamped).
- Left/Right arrow keys step the preview, but NOT while the caret is in the number box or a select.
- Switching template/source resets to label 1; a mapping edit never leaves the index out of range.

- [ ] **Step 7: Commit**

```bash
cd "/c/Users/antho/OneDrive/Documents/Five12-TheApp"
git add app/src/components/DymoPrintDialog.jsx
git commit -m "feat(dymo): jog preview through every merged label (pager + arrows)"
```

---

### Task 3: Print scope (All / Custom page-range)

**Files:**
- Modify: `app/src/components/DymoPrintDialog.jsx`

**Interfaces:**
- Consumes: `parseRangeExpr` (Task 1), `records` memo, `printMerge`.
- Produces: `printList` (the sliced array actually printed).

- [ ] **Step 1: Import the parser**

At the top of the file, after the existing `dymo` import (line 2), add:

```jsx
import { parseRangeExpr } from '../lib/rangeExpr';
```

- [ ] **Step 2: Add scope state**

Next to `previewIndex` (from Task 2), add:

```jsx
  const [scopeMode, setScopeMode] = useState('all');   // 'all' | 'custom'
  const [rangeExpr, setRangeExpr] = useState('');
```

- [ ] **Step 3: Compute the print list**

Immediately after the `records` memo, add:

```jsx
  const printList = useMemo(() => {
    if (scopeMode === 'all') return records;
    return parseRangeExpr(rangeExpr, records.length).map(i => records[i]);
  }, [records, scopeMode, rangeExpr]);
```

- [ ] **Step 4: Print the sliced list and guard on its length**

In `doPrint`, change the >200 guard and the `printMerge` argument from `records` to `printList`:

```jsx
  const doPrint = async () => {
    if (printList.length > 200 &&
        !window.confirm(`Print ${printList.length} labels?`)) return;
    setBusy(true); setError(null);
    try {
      await printMerge(printer, tpl.labelXml, printList);
```

(The rest of `doPrint` — printer persistence, mapping save, `onClose` — is unchanged.)

- [ ] **Step 5: Add the scope selector to the footer**

Replace the footer row (currently `<div className="flex items-center justify-between gap-3">` containing the Printer label and the Cancel/Print group, ~lines 236-253) with:

```jsx
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2 text-sm">
              <span className="text-text-muted">Print</span>
              <button type="button" onClick={() => setScopeMode('all')}
                className={`px-3 py-1.5 rounded border ${scopeMode==='all' ? 'border-brand text-brand-hi' : 'border-border text-text-muted'}`}>All</button>
              <button type="button" onClick={() => setScopeMode('custom')}
                className={`px-3 py-1.5 rounded border ${scopeMode==='custom' ? 'border-brand text-brand-hi' : 'border-border text-text-muted'}`}>Custom</button>
              {scopeMode === 'custom' && (
                <span className="flex items-center gap-2">
                  <input type="text" value={rangeExpr} onChange={e => setRangeExpr(e.target.value)}
                    placeholder="2-4, 10-15"
                    className="w-32 bg-bg border border-border rounded px-2 py-1 text-text" />
                  <span className="text-xs text-text-muted">{printList.length} labels</span>
                </span>
              )}
            </div>
            <label className="flex items-center gap-2 text-sm text-text-muted">
              Printer
              <select value={printer} onChange={e => setPrinter(e.target.value)}
                className="bg-bg border border-border rounded px-2 py-1 text-text">
                {printers.length === 0 && <option value="">none found</option>}
                {printers.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
            </label>
          </div>
          <div className="flex gap-3">
            <button onClick={onClose} className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm">Cancel</button>
            <button onClick={doPrint}
              disabled={busy || !tpl || !printer || printList.length === 0 || ready !== true}
              className="px-4 py-2 bg-online hover:brightness-110 text-bg rounded text-sm font-medium disabled:opacity-40">
              {busy ? 'Printing…' : (scopeMode === 'all' ? `Print all ${records.length}` : `Print ${printList.length} labels`)}
            </button>
          </div>
        </div>
```

- [ ] **Step 6: Manual verification in the browser**

With the dialog open on a multi-row source:
- Default is **All**; button reads `Print all N`; behaves exactly as before.
- Click **Custom**: a box appears with placeholder `2-4, 10-15`. Type `2-4, 10-15` → helper reads `9 labels`, button reads `Print 9 labels`.
- `8` → `1 labels`; `10-15, 2-4` prints in that order (confirm on a small physical run); empty or `abc` → `0 labels` and Print is disabled.
- Out-of-range (`50-60` on a 55-row set) trims to the valid subset.
- The jog pager still works and is unaffected by the scope box (they are independent).

- [ ] **Step 7: Commit**

```bash
cd "/c/Users/antho/OneDrive/Documents/Five12-TheApp"
git add app/src/components/DymoPrintDialog.jsx
git commit -m "feat(dymo): All/Custom print scope via page-range expression"
```

---

## Self-Review

**Spec coverage:**
- Preview jog (prev/next, jump box, arrow keys, reset on change) → Task 2. ✓
- Print scope All/Custom with page-range parse, order-as-written, dupes kept, clamp/drop, live count, button label, disable-on-empty, >200 guard on resolved count → Tasks 1 + 3. ✓
- No backend change; `printMerge`/`renderPreview` signatures unchanged (only the passed array differs) → Global Constraints + Task 3 Step 4. ✓
- Mapping table, source, CSV, printer persistence, mapping-save untouched → not modified in any task. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; verification commands have exact expected output.

**Type consistency:** `parseRangeExpr(expr, max) => number[]` (0-based) defined in Task 1, imported and used as `.map(i => records[i])` in Task 3. `previewIndex` 0-based throughout; UI shows `previewIndex + 1`. `scopeMode` values `'all'|'custom'` consistent between state init, selector buttons, `printList` memo, and button label. `printList` defined in Task 3 Step 3, used in Steps 4-5.

**Note on TDD:** Only the pure parser (Task 1) gets an automated check — the repo has no frontend test runner and the UI is inseparable from the live DYMO web service, so Tasks 2-3 are verified manually per the spec's stated fallback. Introducing a test framework is out of scope for this change.
