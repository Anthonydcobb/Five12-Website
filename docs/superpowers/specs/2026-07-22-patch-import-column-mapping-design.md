# Patch Import — smart column mapping

**Date:** 2026-07-22
**Status:** Approved (design) — pending spec review
**Component:** patch-sheet import (backend `routes.py`, frontend patch editor)

## Problem

Importing a patch sheet only works with the app's own Excel export. The current
route (`POST /api/patch-sheets/<id>/import-excel`) is rigid:

- Assumes the header is on **row 5** (`pd.read_excel(..., header=4)`).
- Matches **exact** column names (`Fix #`, `Fix Type`, `Uni`, `Add`, …); anything
  else fails with "column headers not detected".
- Accepts `.xlsx` only.

A user importing **someone else's** patch (from Excel, Google Sheets, or CSV) has
differently-named columns, in different positions, with extra columns that don't
correspond to any of our fields. The importer should map their columns onto ours,
ignore the rest, and fill in derivable gaps.

## Canonical target fields (`PatchRow`)

`set`, `fixture` (fixture/unit number), `universe`, `address`, `endAddress`,
`type` (fixture type), `channelCount`, `location`, `wattage`, `weight`,
`firmware`, `notes`.

Storage note: `universe`, `address`, `endAddress`, `channelCount` are integers;
`wattage` and `weight` are **strings** in the model; `set` maps to `set_name`,
`endAddress` to `end_address`, `channelCount` to `channel_count`.

## Decisions (from brainstorming)

1. **Auto-guess + confirm screen.** App proposes a mapping; user reviews/edits it
   before committing. Not fully-automatic (too risky on foreign headers), not
   fully-manual (too tedious).
2. **Compute derivable address math.** Fill End Address / Channel Count from each
   other + Address when missing; **never overwrite** a value the sheet provided.
3. **No fixture-library fill in v1.** Import is literal. Library-fill (pull
   ch/W/wt from the fixture library by fixture-type name) is a future feature.
4. **Formats:** `.xlsx` and `.csv` (covers Excel and Google Sheets exports).

## Architecture — two-step, stateless

Replace the one-shot importer with two endpoints. The browser holds the `File`
between the two calls and re-sends it (patch files are small; avoids server
session state).

### `POST /api/patch-sheets/<id>/import/analyze`
Input: uploaded `.xlsx`/`.csv`. **Writes nothing.** Steps:
1. Parse to a raw grid (pandas: `read_excel` or `read_csv` by extension/content).
2. **Detect header row** (see below).
3. Guess a mapping from detected headers → canonical fields (see alias table).
4. Return:
```json
{
  "headerRowIndex": 4,
  "theirColumns": ["Fixture Type", "DMX Addr", "Ch", "Position", "Dimmer"],
  "suggestedMapping": {"Fixture Type": "type", "DMX Addr": "address",
                        "Ch": "channelCount", "Position": "location",
                        "Dimmer": null},
  "previewRows": [ { ...first ~5 rows already mapped to canonical fields... } ],
  "rowCount": 42
}
```

### `POST /api/patch-sheets/<id>/import/commit`
Input: the file **again** + confirmed mapping `{theirHeader: canonicalFieldOrNull}`
+ the detected `headerRowIndex`. Steps:
1. Re-parse with the given `headerRowIndex`.
2. Apply the mapping (ignore any header mapped to `null`).
3. Apply derivation + numeric parsing per row.
4. Skip rows where every mapped field is blank.
5. Insert `PatchRow`s under `<id>`; return `{ "inserted": n, "skipped": m }`.

The old `import-excel` route is retained for backward compatibility with the
app's own exports (can be retired later).

## Header-row detection

Read the first ~15 rows with no header. For each candidate row, normalize its
cells and count how many match a known alias. Choose the row with the highest
match count that also has mostly non-empty cells; tie-break on the earliest row.
Fallback: row 0. This replaces the hardcoded `header=4`.

## Column alias table

Headers are normalized: lowercased, trimmed, punctuation/whitespace collapsed
(e.g. `"ch. count"` → `"ch count"`, `"Fix #"` → `"fix"`). Match normalized header
against each field's alias set; first/best match wins. Ambiguous headers get a
best guess (user fixes on confirm).

| Field | Aliases (normalized) |
|---|---|
| set | set, group, sys, system |
| fixture | fix, fix no, fixture no, fixture number, unit, unit no, chan no, channel no |
| universe | universe, uni, u, net |
| address | address, addr, add, dmx, dmx address, start, start address, patch |
| endAddress | end, end add, end addr, end address, last, last address, thru |
| type | type, fixture type, fixture, model, instrument, instrument type, gear |
| channelCount | ch count, channel count, channels, chans, ch, footprint, dmx footprint, slots |
| location | location, loc, position, pos, area, zone, spot |
| wattage | wattage, watt, watts, power, w |
| weight | weight, wt, mass, lbs, lb, kg |
| firmware | firmware, fw, version, ver |
| notes | notes, note, comment, comments, remark, remarks, desc, description |

Ambiguity handling: a bare `channel`/`ch` is guessed as `channelCount`; a bare
`fixture` is guessed as `type` (most foreign sheets label the fixture-number
column `Fix #`/`Unit`, and the plain word `Fixture` for the model). The confirm
screen exists precisely to correct these.

## Derivation & parsing (commit)

Per row, after mapping:
- Parse `universe`, `address`, `endAddress`, `channelCount` to int where present
  (non-numeric → left blank, no error). `wattage`/`weight` kept as trimmed strings.
- If `address` present and exactly one of {`endAddress`, `channelCount`} present:
  - missing `endAddress` = `address + channelCount − 1`
  - missing `channelCount` = `endAddress − address + 1`
- Never overwrite a provided value; only fill blanks.

## Frontend — `ImportWizard` modal

New component, opened from the existing **Import** control in the patch editor
(`PatchTab.jsx`), now accepting `.csv` too.

- **Step 1 — file:** pick `.xlsx`/`.csv`. On select → call `analyze`.
- **Step 2 — mapping:** a table, one row per *their* column, each with a
  `<select>` of canonical fields + **Ignore**, pre-filled from `suggestedMapping`.
  Below it, a live preview of the first ~5 rows landing in *your* columns.
  - Warn (inline) if two of their columns map to the same target.
  - Show which of their columns are set to Ignore.
  - `Import N rows` button → `commit` → close, refresh the patch rows.
- Design-system styled (surface/border/brand tokens), consistent with the other
  modals.

## Error handling

- No file / unreadable / empty grid → clear error message, wizard stays on step 1.
- No headers confidently detected → still return best-guess (row 0) and let the
  user map manually rather than hard-failing.
- Duplicate target mapping → non-blocking warning; last-wins on commit, but the
  UI nudges the user to fix it.
- Rows with all mapped fields blank → skipped, counted in `skipped`.
- Commit is wrapped in a transaction; any exception → rollback + 500 with message.

## Testing (pytest, existing suite)

- Header detection: header on row 0, row 4, and with junk/title rows above.
- Alias matching: exact, normalized (`ch. Count`), and alias (`DMX Addr`).
- Ignore unmatched: an extra `Dimmer` column is dropped.
- Derivation: addr+count→end, addr+end→count, and "provided value not overwritten".
- CSV and XLSX parity on the same data.
- Blank-row skipping.

## Out of scope (future)

- **Fixture-library fill** — enrich missing ch/W/wt from the fixture library by
  fixture-type name (needs fuzzy name matching).
- **Dedupe/merge** into a non-empty patch — v1 appends; a new patch is empty.
- Saved/remembered mappings per source.
