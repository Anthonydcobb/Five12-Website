import React, { useEffect, useMemo, useRef, useState } from 'react';
import { dymoReady, getPrinters, renderPreview, printMerge } from '../lib/dymo';
import { parseRangeExpr } from '../lib/rangeExpr';

const PATCH_FIELDS = ['set','fixture','universe','address','endAddress','type',
  'channelCount','location','wattage','weight','firmware','notes'];
const LAST_PRINTER_KEY = 'five12_dymo_printer';

async function readJson(res) {                      // same helper as ImportWizard
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON */ }
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
  return data || {};
}

// tiny CSV parse (RFC-4180 quotes) — first row = headers
function parseCsv(text) {
  const rows = []; let row = [], cell = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') q = false;
      else cell += c;
    } else if (c === '"') q = true;
    else if (c === ',') { row.push(cell); cell = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(cell); cell = '';
      if (row.some(v => v !== '')) rows.push(row);
      row = [];
    } else cell += c;
  }
  row.push(cell);
  if (row.some(v => v !== '')) rows.push(row);
  const [headers, ...data] = rows;
  return { headers: headers || [], rows: data.map(r =>
    Object.fromEntries((headers || []).map((h, i) => [h, r[i] ?? '']))) };
}

// auto-guess: normalized variable name vs normalized column names
const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
const GUESS = { fixnum: 'fixture', fix: 'fixture', fixture: 'fixture',
  uni: 'universe', universe: 'universe', addr: 'address', address: 'address',
  add: 'address', endaddr: 'endAddress', type: 'type', fixturetype: 'type',
  ch: 'channelCount', chcount: 'channelCount', loc: 'location',
  location: 'location', position: 'location', watt: 'wattage',
  wattage: 'wattage', weight: 'weight', notes: 'notes', name: 'type' };
function guessMapping(variables, columns) {
  const byNorm = Object.fromEntries(columns.map(c => [norm(c), c]));
  const out = {};
  for (const v of variables) {
    const n = norm(v);
    out[v] = byNorm[n] || byNorm[norm(GUESS[n] || '')] ||
             (GUESS[n] && columns.includes(GUESS[n]) ? GUESS[n] : '') || '';
  }
  return out;
}

// prefill mapping from a template's saved mappings for this source, falling back to a guess
const deriveMapping = (t, srcKey, cols) => {
  const saved = (t.savedMappings || {})[srcKey];
  return saved && Object.keys(saved).length
    ? Object.fromEntries(t.variables.map(v => [v, cols.includes(saved[v]) ? saved[v] : '']))
    : guessMapping(t.variables, cols);
};

export default function DymoPrintDialog({ patchRows, selectedRows, onClose }) {
  const [ready, setReady] = useState(null);          // null=probing
  const [templates, setTemplates] = useState([]);
  const [tpl, setTpl] = useState(null);              // full record incl labelXml
  const [source, setSource] = useState(patchRows ? 'sheet' : 'csv'); // sheet|selection|csv
  const [csv, setCsv] = useState(null);              // {headers, rows}
  const [recentCsvs, setRecentCsvs] = useState([]);
  const [mapping, setMapping] = useState({});        // {var: column}
  const [printers, setPrinters] = useState([]);
  const [printer, setPrinter] = useState(localStorage.getItem(LAST_PRINTER_KEY) || '');
  const [roll, setRoll] = useState('Left');               // TwinTurbo roll, per printer
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [previewIndex, setPreviewIndex] = useState(0);
  const [scopeMode, setScopeMode] = useState('all');   // 'all' | 'custom'
  const [rangeExpr, setRangeExpr] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [printedMsg, setPrintedMsg] = useState(null);
  const [progress, setProgress] = useState(null);   // {printed, total} while running
  const abortRef = useRef(null);

  const probe = async () => {
    setReady(null);
    const ok = await dymoReady();
    setReady(ok);
    if (ok) {
      try {
        const ps = await getPrinters();
        setPrinters(ps);
        if (ps.length && !ps.some(p => p.name === printer)) setPrinter(ps[0].name);
      } catch { setPrinters([]); }
    }
  };
  useEffect(() => { probe(); }, []);
  const selectedPrinter = printers.find(p => p.name === printer);
  useEffect(() => {
    if (printer) setRoll(localStorage.getItem(`five12_dymo_roll:${printer}`) || 'Left');
  }, [printer]);
  const pickRoll = (r) => {
    setRoll(r);
    localStorage.setItem(`five12_dymo_roll:${printer}`, r);
  };
  useEffect(() => {
    fetch('/api/dymo-templates').then(readJson).then(setTemplates).catch(e => setError(e.message));
  }, []);
  const loadRecentCsvs = () =>
    fetch('/api/dymo-csv-sources').then(readJson).then(setRecentCsvs).catch(() => {});
  useEffect(() => { loadRecentCsvs(); }, []);

  const columns = source === 'csv' ? (csv?.headers || []) : PATCH_FIELDS;
  const rows = source === 'csv' ? (csv?.rows || [])
    : source === 'selection' ? selectedRows : (patchRows || []);
  const records = useMemo(() => {
    if (!tpl) return [];
    return rows.map((r) => {
      const rec = {};
      for (const [v, col] of Object.entries(mapping)) {
        if (col) rec[v] = String(r[col] ?? '');
      }
      return Object.values(rec).some((x) => x !== '') ? rec : null;
    }).filter(Boolean);
  }, [rows, mapping, tpl]);

  const printList = useMemo(() => {
    if (scopeMode === 'all') return records;
    return parseRangeExpr(rangeExpr, records.length).map(i => records[i]);
  }, [records, scopeMode, rangeExpr]);

  // jump back to the first label on a structural source/template change
  useEffect(() => { setPreviewIndex(0); }, [tpl, source, csv]);
  // keep the index valid if the record count shrinks (e.g. mapping edit)
  useEffect(() => {
    setPreviewIndex(i => Math.min(Math.max(i, 0), Math.max(0, records.length - 1)));
  }, [records.length]);

  const pickTemplate = async (id) => {
    setError(null); setPreview(null); setPreviewError(null);
    if (!id) { setTpl(null); return; }
    try {
      const t = await fetch(`/api/dymo-templates/${id}`).then(readJson);
      setTpl(t);
      setMapping(deriveMapping(t, source === 'csv' ? 'csv' : 'patch', columns));
    } catch (e) { setError(e.message); }
  };

  const loadRecentCsv = async (id) => {
    try {
      const full = await fetch(`/api/dymo-csv-sources/${id}`).then(readJson);
      setCsv({ headers: full.headers, rows: full.rows });
      setSource('csv');
    } catch (e) { setError(e.message); }
  };

  const deleteRecentCsv = async (id, ev) => {
    ev.stopPropagation();
    try {
      await fetch(`/api/dymo-csv-sources/${id}`, { method: 'DELETE' }).then(readJson);
      loadRecentCsvs();
    } catch (e) { setError(e.message); }
  };

  // re-derive the mapping whenever the source context changes while a template is selected
  useEffect(() => {
    if (!tpl) return;
    const srcKey = source === 'csv' ? 'csv' : 'patch';
    setMapping(deriveMapping(tpl, srcKey, source === 'csv' ? (csv?.headers || []) : PATCH_FIELDS));
  }, [source, csv]);   // intentionally not on tpl — pickTemplate handles that

  // live preview of the currently-jogged record
  useEffect(() => {
    if (!tpl || !records.length || ready !== true) {
      setPreview(null); setPreviewError(null); return;
    }
    const rec = records[Math.min(previewIndex, records.length - 1)];
    let alive = true;
    renderPreview(tpl.labelXml, rec)
      .then(png => { if (alive) { setPreview(png); setPreviewError(null); } })
      .catch(err => {
        // Never swallow this. On DYMO Connect 1.6.1.7 RenderLabel is dead (see
        // lib/dymo.js), and a silent failure left the pane showing "preview
        // appears when mapped" — blaming the user for a service fault.
        console.error('DYMO label preview failed:', err);
        if (alive) { setPreview(null); setPreviewError(err); }
      });
    return () => { alive = false; };
  }, [tpl, records, previewIndex, ready]);

  // left/right arrows step the preview, unless focus is in an input/select
  useEffect(() => {
    const max = Math.max(0, records.length - 1);
    const onKey = (e) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return;
      if (busy) return; // renderPreview is a synchronous XHR — jogging mid-run blocks the tab
      if (e.key === 'ArrowLeft') setPreviewIndex(i => Math.max(0, i - 1));
      else if (e.key === 'ArrowRight') setPreviewIndex(i => Math.max(0, Math.min(max, i + 1)));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [records.length, busy]);

  // clear the "Printed" confirmation once the print context changes
  useEffect(() => { setPrintedMsg(null); }, [tpl, source, csv, scopeMode, rangeExpr]);

  const doPrint = async () => {
    if (printList.length > 200 &&
        !window.confirm(`Print ${printList.length} labels?`)) return;
    setBusy(true); setError(null); setPrintedMsg(null);
    setProgress({ printed: 0, total: printList.length });
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const res = await printMerge(printer, tpl.labelXml, printList, {
        roll: selectedPrinter?.isTwinTurbo ? roll : undefined,
        signal: ac.signal,
        onProgress: setProgress,
      });
      localStorage.setItem(LAST_PRINTER_KEY, printer);
      if (res.printed > 0) {
        // labels came out — worth remembering the mapping even on a stopped run
        try {
          const srcKey = source === 'csv' ? 'csv' : 'patch';
          await fetch(`/api/dymo-templates/${tpl.id}/mapping`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: srcKey, mapping }) }).then(readJson);
        } catch (e) {
          console.warn('mapping save failed (labels already printed):', e);
        }
      }
      if (res.reason) {
        setError(`${res.reason} — stopped after ${res.printed} of ${res.total}.`);
      } else if (res.stopped) {
        setPrintedMsg(`Stopped — ${res.printed} of ${res.total} printed.`);
      } else {
        setPrintedMsg(`Printed ${res.total} label${res.total === 1 ? '' : 's'}.`);
      }
    } catch (e) { setError(e.message); }
    finally { setBusy(false); setProgress(null); abortRef.current = null; }
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-surface border border-border rounded-lg p-6 w-[min(92vw,760px)] max-h-[88vh] overflow-auto shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Print DYMO Labels</h3>
          <button onClick={onClose} disabled={busy}
            className="text-text-muted hover:text-text text-lg leading-none disabled:opacity-40">×</button>
        </div>

        {error && <div className="bg-brand-dim/30 border border-brand/40 text-brand-hi text-sm rounded px-3 py-2 mb-3">{error}</div>}

        {printedMsg && <div className="bg-online/15 border border-online/40 text-online text-sm rounded px-3 py-2 mb-3">{printedMsg}</div>}

        {ready === false && (
          <div className="bg-warn/15 border border-warn/40 text-warn text-sm rounded px-3 py-2 mb-3 flex items-center justify-between">
            <span>DYMO Connect isn't running — launch DYMO Connect, then retry.</span>
            <button onClick={probe} className="px-3 py-1 bg-surface-2 hover:bg-border rounded text-text text-xs">Retry</button>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
          <label className="block">
            <span className="text-xs text-text-muted mb-1 block">Template</span>
            <select onChange={e => pickTemplate(e.target.value)} value={tpl?.id || ''}
              className="w-full bg-bg border border-border rounded px-2 py-1.5 text-text text-sm">
              <option value="">Choose…</option>
              {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
          <div className="block">
            <span className="text-xs text-text-muted mb-1 block">Source</span>
            <div className="flex gap-2 text-sm">
              {patchRows && <button onClick={() => setSource('sheet')}
                className={`px-3 py-1.5 rounded border ${source==='sheet' ? 'border-brand text-brand-hi' : 'border-border text-text-muted'}`}>
                Sheet ({patchRows.length})</button>}
              {selectedRows?.length > 0 && <button onClick={() => setSource('selection')}
                className={`px-3 py-1.5 rounded border ${source==='selection' ? 'border-brand text-brand-hi' : 'border-border text-text-muted'}`}>
                Selected ({selectedRows.length})</button>}
              <label className={`px-3 py-1.5 rounded border cursor-pointer ${source==='csv' ? 'border-brand text-brand-hi' : 'border-border text-text-muted'}`}>
                CSV…
                <input type="file" accept=".csv" className="hidden" onChange={async e => {
                  const f = e.target.files[0];
                  if (!f) return;
                  const parsed = parseCsv(await f.text());
                  setCsv(parsed);
                  setSource('csv');
                  e.target.value = '';
                  // remember this CSV for reprinting (never blocks printing)
                  fetch('/api/dymo-csv-sources', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: f.name, headers: parsed.headers, rows: parsed.rows }),
                  }).then(readJson).then(loadRecentCsvs).catch(e => console.warn('CSV history save failed:', e));
                }} />
              </label>
            </div>
            {recentCsvs.length > 0 && (
              <div className="mt-2 border border-border rounded max-h-40 overflow-auto">
                <div className="text-xs text-text-muted px-2 py-1 border-b border-border">Recent CSVs</div>
                {recentCsvs.map(rc => (
                  <div key={rc.id} onClick={() => loadRecentCsv(rc.id)}
                    className="flex items-center justify-between gap-2 px-2 py-1 text-sm cursor-pointer hover:bg-surface-2">
                    <span className="truncate">{rc.name}</span>
                    <span className="flex items-center gap-2 shrink-0">
                      <span className="text-xs text-text-muted">{rc.rowCount} rows · {new Date(rc.createdAt).toLocaleDateString()}</span>
                      <button type="button" aria-label={`delete ${rc.name}`}
                        onClick={(ev) => deleteRecentCsv(rc.id, ev)}
                        className="text-text-muted hover:text-brand-hi leading-none">×</button>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {tpl && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
            <table className="text-sm self-start">
              <thead><tr className="text-text-muted text-xs uppercase tracking-wide">
                <th className="text-left py-1">Text box</th><th className="text-left py-1">← Column</th></tr></thead>
              <tbody>
                {tpl.variables.map(v => (
                  <tr key={v} className="border-t border-border">
                    <td className="py-1.5 pr-3 font-mono">{v}</td>
                    <td className="py-1.5">
                      <select value={mapping[v] || ''} onChange={e => setMapping(m => ({ ...m, [v]: e.target.value }))}
                        className="bg-bg border border-border rounded px-2 py-1 text-text">
                        <option value="">— blank —</option>
                        {columns.map(c => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex flex-col gap-2">
              <div className="bg-bg border border-border rounded-lg p-3 flex items-center justify-center min-h-[140px]">
                {preview ? (
                  <img alt="label preview" className="max-w-full max-h-[220px]" src={`data:image/png;base64,${preview}`} />
                ) : previewError ? (
                  <div className="text-center px-2" title={String(previewError.message || previewError)}>
                    <div className="text-warn text-xs font-medium">Preview unavailable</div>
                    <div className="text-text-muted text-[11px] mt-1 leading-snug">
                      Quit and relaunch DYMO Connect, then reopen this dialog —
                      its render service gets into a state where it fails every
                      label until restarted. Printing is unaffected.
                    </div>
                  </div>
                ) : (
                  <span className="text-text-muted text-xs">preview appears when mapped</span>
                )}
              </div>
              {records.length > 0 && (
                <div className="flex items-center justify-center gap-2 text-sm text-text-muted">
                  <button type="button" aria-label="previous label"
                    onClick={() => setPreviewIndex(i => Math.max(0, i - 1))}
                    disabled={previewIndex <= 0 || busy}
                    className="px-2 py-0.5 rounded border border-border disabled:opacity-30 hover:bg-surface-2">‹</button>
                  <span className="flex items-center gap-1">
                    Label
                    <input type="number" min={1} max={records.length} value={previewIndex + 1}
                      disabled={busy}
                      onChange={e => {
                        const n = parseInt(e.target.value, 10);
                        if (!Number.isNaN(n)) setPreviewIndex(Math.min(records.length - 1, Math.max(0, n - 1)));
                      }}
                      className="w-14 bg-bg border border-border rounded px-1 py-0.5 text-center text-text" />
                    of {records.length}
                  </span>
                  <button type="button" aria-label="next label"
                    onClick={() => setPreviewIndex(i => Math.min(records.length - 1, i + 1))}
                    disabled={previewIndex >= records.length - 1 || busy}
                    className="px-2 py-0.5 rounded border border-border disabled:opacity-30 hover:bg-surface-2">›</button>
                </div>
              )}
            </div>
          </div>
        )}

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
                {printers.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
              </select>
            </label>
            {selectedPrinter?.isTwinTurbo && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-text-muted">Roll</span>
                <button type="button" onClick={() => pickRoll('Left')}
                  className={`px-3 py-1.5 rounded border ${roll==='Left' ? 'border-brand text-brand-hi' : 'border-border text-text-muted'}`}>Left</button>
                <button type="button" onClick={() => pickRoll('Right')}
                  className={`px-3 py-1.5 rounded border ${roll==='Right' ? 'border-brand text-brand-hi' : 'border-border text-text-muted'}`}>Right</button>
              </div>
            )}
          </div>
          <div className="flex items-center gap-3">
            {busy && progress && (
              <span className="text-sm text-text-muted">
                Printing {Math.min(progress.printed + 1, progress.total)} of {progress.total}…
              </span>
            )}
            <button onClick={onClose} disabled={busy}
              className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm disabled:opacity-40">Cancel</button>
            {busy ? (
              <button onClick={() => abortRef.current?.abort()}
                className="px-4 py-2 bg-brand-dim/40 border border-brand/40 text-brand-hi hover:bg-brand-dim/60 rounded text-sm font-medium">
                Stop
              </button>
            ) : (
              <button onClick={doPrint}
                disabled={!tpl || !printer || printList.length === 0 || ready !== true}
                className="px-4 py-2 bg-online hover:brightness-110 text-bg rounded text-sm font-medium disabled:opacity-40">
                {scopeMode === 'all' ? `Print all ${records.length}` : `Print ${printList.length} labels`}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
