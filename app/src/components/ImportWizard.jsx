import React, { useState } from 'react';

const FIELDS = [
  ['set', 'Set'], ['fixture', 'Fix #'], ['universe', 'Universe'],
  ['address', 'Address'], ['endAddress', 'End Addr'], ['type', 'Fixture Type'],
  ['channelCount', 'CH Count'], ['location', 'Location'], ['wattage', 'Wattage'],
  ['weight', 'Weight'], ['firmware', 'Firmware'], ['notes', 'Notes'],
];
const LABEL = Object.fromEntries(FIELDS);

export default function ImportWizard({ patchId, onClose, onImported }) {
  const [file, setFile] = useState(null);
  const [analysis, setAnalysis] = useState(null);   // analyze response
  const [mapping, setMapping] = useState({});       // {header: field|null}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const analyze = async (f) => {
    setBusy(true); setError(null);
    try {
      const fd = new FormData();
      fd.append('file', f);
      const res = await fetch(`/api/patch-sheets/${patchId}/import/analyze`,
                             { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Analyze failed');
      setAnalysis(data);
      setMapping(data.suggestedMapping || {});
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const onPick = (e) => {
    const f = e.target.files[0];
    if (!f) return;
    setFile(f);
    analyze(f);
  };

  const commit = async () => {
    setBusy(true); setError(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('mapping', JSON.stringify(mapping));
      fd.append('headerRowIndex', String(analysis.headerRowIndex));
      const res = await fetch(`/api/patch-sheets/${patchId}/import/commit`,
                             { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Import failed');
      onImported(data.inserted);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  // duplicate-target detection
  const targets = Object.values(mapping).filter(Boolean);
  const dupes = targets.filter((t, i) => targets.indexOf(t) !== i);

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-surface border border-border rounded-lg p-6 w-[min(90vw,720px)] max-h-[85vh] overflow-auto shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Import Patch Sheet</h3>
          <button onClick={onClose} className="text-text-muted hover:text-text text-lg leading-none">×</button>
        </div>

        {error && (
          <div className="bg-brand-dim/30 border border-brand/40 text-brand-hi text-sm rounded px-3 py-2 mb-3">{error}</div>
        )}

        {!analysis ? (
          <label className="block border border-dashed border-border rounded-lg p-8 text-center cursor-pointer hover:border-muted">
            <div className="text-text-muted text-sm">Choose an .xlsx or .csv patch sheet</div>
            <input type="file" accept=".xlsx,.csv" className="hidden" onChange={onPick} />
          </label>
        ) : (
          <>
            <p className="text-text-muted text-sm mb-3">
              {analysis.rowCount} rows · header row {analysis.headerRowIndex + 1}. Map their columns to yours:
            </p>
            {dupes.length > 0 && (
              <div className="bg-warn/15 border border-warn/40 text-warn text-xs rounded px-3 py-2 mb-3">
                Two columns map to the same field ({[...new Set(dupes)].map(d => LABEL[d]).join(', ')}); the last one wins.
              </div>
            )}
            <table className="w-full text-sm mb-4">
              <thead>
                <tr className="text-text-muted text-xs uppercase tracking-wide">
                  <th className="text-left py-1">Their column</th>
                  <th className="text-left py-1">→ Your column</th>
                  <th className="text-left py-1">Sample</th>
                </tr>
              </thead>
              <tbody>
                {analysis.theirColumns.map(col => (
                  <tr key={col} className="border-t border-border">
                    <td className="py-1.5 pr-3 font-mono">{col}</td>
                    <td className="py-1.5 pr-3">
                      <select
                        value={mapping[col] || 'ignore'}
                        onChange={e => setMapping(m => ({ ...m, [col]: e.target.value === 'ignore' ? null : e.target.value }))}
                        className="bg-bg border border-border rounded px-2 py-1 text-text"
                      >
                        <option value="ignore">— Ignore —</option>
                        {FIELDS.map(([k, lbl]) => <option key={k} value={k}>{lbl}</option>)}
                      </select>
                    </td>
                    <td className="py-1.5 text-text-muted font-mono truncate max-w-[180px]">
                      {String(analysis.previewRows[0]?.[col] ?? '')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex justify-end gap-3">
              <button onClick={onClose} className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm">Cancel</button>
              <button onClick={commit} disabled={busy}
                className="px-4 py-2 bg-online hover:brightness-110 text-bg rounded text-sm font-medium disabled:opacity-40">
                {busy ? 'Importing…' : `Import ${analysis.rowCount} rows`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
