import React, { useEffect, useMemo, useState } from 'react';
import { dymoReady, getPrinters, renderPreview, printMerge } from '../lib/dymo';

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

export default function DymoPrintDialog({ patchRows, selectedRows, onClose }) {
  const [ready, setReady] = useState(null);          // null=probing
  const [templates, setTemplates] = useState([]);
  const [tpl, setTpl] = useState(null);              // full record incl labelXml
  const [source, setSource] = useState(patchRows ? 'sheet' : 'csv'); // sheet|selection|csv
  const [csv, setCsv] = useState(null);              // {headers, rows}
  const [mapping, setMapping] = useState({});        // {var: column}
  const [printers, setPrinters] = useState([]);
  const [printer, setPrinter] = useState(localStorage.getItem(LAST_PRINTER_KEY) || '');
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const probe = async () => {
    setReady(null);
    const ok = await dymoReady();
    setReady(ok);
    if (ok) {
      const ps = await getPrinters();
      setPrinters(ps);
      if (ps.length && !ps.includes(printer)) setPrinter(ps[0]);
    }
  };
  useEffect(() => { probe(); }, []);
  useEffect(() => {
    fetch('/api/dymo-templates').then(readJson).then(setTemplates).catch(e => setError(e.message));
  }, []);

  const columns = source === 'csv' ? (csv?.headers || []) : PATCH_FIELDS;
  const rows = source === 'csv' ? (csv?.rows || [])
    : source === 'selection' ? selectedRows : (patchRows || []);
  const records = useMemo(() => rows.map(r =>
    Object.fromEntries(Object.entries(mapping)
      .filter(([, col]) => col)
      .map(([v, col]) => [v, String(r[col] ?? '')])))
    .filter(rec => Object.values(rec).some(v => v !== '')), [rows, mapping]);

  const pickTemplate = async (id) => {
    setError(null); setPreview(null);
    if (!id) { setTpl(null); return; }
    try {
      const t = await fetch(`/api/dymo-templates/${id}`).then(readJson);
      setTpl(t);
      const srcKey = source === 'csv' ? 'csv' : 'patch';
      const saved = (t.savedMappings || {})[srcKey];
      setMapping(saved && Object.keys(saved).length
        ? Object.fromEntries(t.variables.map(v => [v, columns.includes(saved[v]) ? saved[v] : '']))
        : guessMapping(t.variables, columns));
    } catch (e) { setError(e.message); }
  };

  // live preview of the first record
  useEffect(() => {
    if (!tpl || !records.length || ready !== true) { setPreview(null); return; }
    let alive = true;
    renderPreview(tpl.labelXml, records[0])
      .then(png => { if (alive) setPreview(png); })
      .catch(() => { if (alive) setPreview(null); });
    return () => { alive = false; };
  }, [tpl, records, ready]);

  const doPrint = async () => {
    if (records.length > 200 &&
        !window.confirm(`Print ${records.length} labels?`)) return;
    setBusy(true); setError(null);
    try {
      await printMerge(printer, tpl.labelXml, records);
      localStorage.setItem(LAST_PRINTER_KEY, printer);
      const srcKey = source === 'csv' ? 'csv' : 'patch';
      await fetch(`/api/dymo-templates/${tpl.id}/mapping`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: srcKey, mapping }) }).then(readJson);
      onClose();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-surface border border-border rounded-lg p-6 w-[min(92vw,760px)] max-h-[88vh] overflow-auto shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Print DYMO Labels</h3>
          <button onClick={onClose} className="text-text-muted hover:text-text text-lg leading-none">×</button>
        </div>

        {error && <div className="bg-brand-dim/30 border border-brand/40 text-brand-hi text-sm rounded px-3 py-2 mb-3">{error}</div>}

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
          <label className="block">
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
                  setCsv(parseCsv(await f.text()));
                  setSource('csv');
                }} />
              </label>
            </div>
          </label>
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
            <div className="bg-bg border border-border rounded-lg p-3 flex items-center justify-center min-h-[140px]">
              {preview
                ? <img alt="label preview" className="max-w-full max-h-[220px]" src={`data:image/png;base64,${preview}`} />
                : <span className="text-text-muted text-xs">preview appears when mapped</span>}
            </div>
          </div>
        )}

        <div className="flex items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm text-text-muted">
            Printer
            <select value={printer} onChange={e => setPrinter(e.target.value)}
              className="bg-bg border border-border rounded px-2 py-1 text-text">
              {printers.length === 0 && <option value="">none found</option>}
              {printers.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <div className="flex gap-3">
            <button onClick={onClose} className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm">Cancel</button>
            <button onClick={doPrint}
              disabled={busy || !tpl || !printer || records.length === 0 || ready !== true}
              className="px-4 py-2 bg-online hover:brightness-110 text-bg rounded text-sm font-medium disabled:opacity-40">
              {busy ? 'Printing…' : `Print ${records.length} labels`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
