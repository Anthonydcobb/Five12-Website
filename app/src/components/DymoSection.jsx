import React, { useEffect, useState } from 'react';
import DymoPrintDialog from './DymoPrintDialog';

async function readJson(res) {
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON */ }
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
  return data || {};
}

export default function DymoSection() {
  const [templates, setTemplates] = useState([]);
  const [error, setError] = useState(null);
  const [showPrint, setShowPrint] = useState(false);

  const load = () => fetch('/api/dymo-templates').then(readJson)
    .then(setTemplates).catch(e => setError(e.message));
  useEffect(() => { load(); }, []);

  const upload = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    setError(null);
    try {
      const fd = new FormData();
      fd.append('file', f);
      await fetch('/api/dymo-templates', { method: 'POST', body: fd }).then(readJson);
      load();
    } catch (err) { setError(err.message); }
    e.target.value = '';
  };

  const remove = async (id) => {
    if (!window.confirm('Delete this DYMO template?')) return;
    try { await fetch(`/api/dymo-templates/${id}`, { method: 'DELETE' }).then(readJson); load(); }
    catch (err) { setError(err.message); }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-text-muted uppercase tracking-wider">DYMO Templates</h2>
        <div className="flex gap-3">
          <label className="text-xs px-3 py-1.5 bg-brand hover:bg-brand-hi text-white rounded cursor-pointer">
            Upload .dymo
            <input type="file" accept=".dymo,.label,.xml" className="hidden" onChange={upload} />
          </label>
          <button onClick={() => setShowPrint(true)}
            className="text-xs px-3 py-1.5 bg-online hover:brightness-110 text-bg rounded font-medium">
            Print from CSV
          </button>
        </div>
      </div>
      {error && <div className="bg-brand-dim/30 border border-brand/40 text-brand-hi text-xs rounded px-3 py-2">{error}</div>}
      {templates.length === 0
        ? <p className="text-text-muted text-sm">No templates yet. Design one in DYMO Connect (name every text box), then upload it here.</p>
        : (
          <div className="space-y-2">
            {templates.map(t => (
              <div key={t.id} className="flex items-center justify-between bg-surface border border-border rounded-lg px-4 py-3">
                <div>
                  <span className="font-medium text-sm">{t.name}</span>
                  <div className="font-mono text-xs text-text-muted mt-0.5">vars: {t.variables.join(', ')}</div>
                </div>
                <button onClick={() => remove(t.id)} className="text-xs px-2 py-1.5 text-text-muted hover:text-brand-hi rounded">×</button>
              </div>
            ))}
          </div>
        )}
      {showPrint && <DymoPrintDialog patchRows={null} selectedRows={[]} onClose={() => setShowPrint(false)} />}
    </div>
  );
}
