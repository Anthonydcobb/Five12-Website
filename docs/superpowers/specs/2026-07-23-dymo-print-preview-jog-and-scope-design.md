# DYMO Print Dialog — preview jog + print scope

Date: 2026-07-23
Component: `app/src/components/DymoPrintDialog.jsx` (frontend only, no backend change)
Branch: `feat/dymo-label-merge` (extends the unmerged DYMO mail-merge feature)

## Problem

The Print DYMO Labels dialog has two gaps found during the pre-merge review:

1. **The preview only ever shows the first label.** `records[0]` is hard-rendered,
   so there is no way to check that labels 2..N merged correctly before committing
   a whole roll.
2. **Print is all-or-nothing.** `printMerge(printer, labelXml, records)` always sends
   every record; the button reads `Print N labels` with no way to print a subset.

## Goals

- Step through (jog) every merged label in the preview to eyeball each one.
- Choose what to print: everything, or an arbitrary set expressed like a printer
  page range (`2-4, 10-15, 20`).

Non-goals: batching multiple labels into one print job (the format's native merge is
broken — one job per label stays); selecting by data value (fixture #, address); any
backend/API change.

## Design

### Records model (unchanged)

`records` is the existing memoized array of merged label objects — one per source row
that produced any non-blank mapped value (blank rows already filtered out in
`records`). All positions below are **1-based indices into `records`**; `N =
records.length`. When the record set changes (template / source / mapping edit), the
jog index resets to 1.

### Preview jog

- New state `previewIndex` (0-based internally, shown 1-based).
- Preview renders `records[previewIndex]` instead of `records[0]`.
- Pager UI under the preview image: `‹  Label [n] of N  ›`
  - Prev / next buttons step by one; disabled at the ends.
  - `n` is a small editable number input — typing a value jumps directly to it,
    clamped to [1, N].
  - Left / right arrow keys step prev/next when the dialog has focus and the event
    target is not an input/select (so typing in the range box isn't hijacked).
- Purely a viewing aid — it does **not** affect what prints.

### Print scope

Two-way selector styled like the existing Source buttons:

- **All** (default) — prints every record.
- **Custom** — a text box taking a page-range expression, e.g. `2-4, 10-15, 20`.

Parsing (`parseRangeExpr(expr, max) -> number[]` of 0-based indices):

- Split on commas; trim each token.
- A token `a-b` expands to a..b inclusive in the written direction (`10-15` → 10..15).
  A bare token `k` is the single position k.
- Each produced position is clamped to [1, max]; positions outside are dropped.
- **Order = as written** (`10-15, 2-4` → 10..15 then 2..4). **Duplicates kept**
  (`5, 5` → #5 twice). No sort, no dedupe.
- Non-numeric / malformed tokens are ignored. If the whole expression yields zero
  positions, the result is empty.

Resolved print list:

- All mode → `records`.
- Custom mode → `parseRangeExpr(expr, N).map(i => records[i])`.

### Button + validation

- Green button label reflects the resolved count: `Print all 55` (All) /
  `Print 9 labels` (Custom). Live "N labels" helper text next to the Custom box.
- Print is disabled when: busy, no template, no printer, DYMO not ready, `N === 0`,
  or (Custom mode) the expression resolves to zero positions.
- The existing >200-label `window.confirm` guard stays, keyed on the resolved
  print-list length (not `records.length`).

### Placement

- Jog pager: inside the right-column preview panel, directly under the image.
- Scope selector + Custom box: in the footer row, left of the Printer dropdown, so
  the print decision reads left-to-right: `Scope · Printer · Cancel · Print`.

## What stays the same

- Mapping table, source selection, CSV parsing, template fetch, live-render effect
  (now keyed on `previewIndex` too), printer selection + `LAST_PRINTER_KEY`,
  mapping-save-after-print (`PUT /mapping`), and error handling are untouched.
- `printMerge` / `renderPreview` / `dymo` lib signatures are unchanged; only the
  array passed to `printMerge` is now a slice.

## Testing

Manual (dialog is browser/DYMO-service dependent), on the real "LZMU Dymo Label Big"
template with a multi-row patch/CSV source:

1. Jog: prev/next moves through all N previews; ends disable correctly; typing a
   number jumps; arrow keys step; index resets to 1 on template/source change.
2. Custom parse: `2-4, 10-15` → helper shows 9; `8` → 1; `10-15, 2-4` prints in that
   order; `5,5` → 2; empty / `abc` → Print disabled; out-of-range trimmed to [1, N].
3. Print sends exactly the resolved subset (verify count in the DYMO job / physically
   on a small set). All mode unchanged from today.
4. Regression: All-mode print, mapping save, preview render, printer persistence all
   still work.

Pure helper `parseRangeExpr` is unit-testable independently of the dialog; add a small
test if a frontend test setup exists, otherwise rely on the manual matrix above.
