import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';

import LabelDesigner  from '../components/LabelDesigner';
import LabelPreview   from '../components/LabelPreview';
import { generateLabelsPDF, AVERY } from '../utils/labelPdf';

// Only show one entry per unique size (skip 8xxx duplicates in the picker)
const SIZES = [
  '5160','5161','5162','5163','5164','5167','5168','5195',
].map(id => ({ id, ...AVERY[id] }));

export default function LabelsPage() {
  const [view, setView] = useState('design');

  // ── Template state ──────────────────────────────────────
  const [templates, setTemplates]     = useState([]);
  const [openMenuId, setOpenMenuId]   = useState(null);
  const [selectedTpl, setSelectedTpl] = useState(null);   // null = no template open
  const [templateConfig, setTemplateConfig] = useState({ fields: [] });
  const [labelSize, setLabelSize]     = useState('5161');

  // ── Save-name flow ──────────────────────────────────────
  const [namingMode, setNamingMode]   = useState(false);  // show inline name input
  const [draftName, setDraftName]     = useState('');
  const nameInputRef = useRef(null);

  useEffect(() => {
    if (namingMode) nameInputRef.current?.focus();
  }, [namingMode]);

  useEffect(() => {
    axios.get('/api/label-templates').then(r => setTemplates(r.data)).catch(console.error);
  }, []);

  // ── Patch state ─────────────────────────────────────────
  const [shows, setShows]               = useState([]);
  const [selectedShow, setSelectedShow] = useState('');
  const [patches, setPatches]           = useState([]);
  const [selectedPatch, setSelectedPatch] = useState('');
  const [rows, setRows]                 = useState([]);
  const [typeFilter, setTypeFilter]     = useState('');
  const [selectedRowIds, setSelectedRowIds] = useState([]);

  useEffect(() => { axios.get('/api/shows').then(r => setShows(r.data)).catch(console.error); }, []);

  useEffect(() => {
    if (!selectedShow) { setPatches([]); setSelectedPatch(''); return; }
    axios.get(`/api/shows/${selectedShow}/patch-sheets`).then(r => setPatches(r.data)).catch(console.error);
  }, [selectedShow]);

  useEffect(() => {
    if (!selectedPatch) { setRows([]); setSelectedRowIds([]); return; }
    axios.get(`/api/patch-sheets/${selectedPatch}/rows`).then(r => setRows(r.data)).catch(console.error);
  }, [selectedPatch]);

  // ── Preview ─────────────────────────────────────────────
  const [previewActive, setPreviewActive] = useState(false);
  const [previewIndex, setPreviewIndex]   = useState(0);
  const selectedRows = rows.filter(r => selectedRowIds.includes(r.id));
  const canPrev = previewIndex > 0;
  const canNext = previewIndex < selectedRows.length - 1;
  useEffect(() => { if (previewActive) setPreviewIndex(0); }, [previewActive]);

  // ── Row helpers ─────────────────────────────────────────
  const toggleRow   = (id, on) => setSelectedRowIds(rs => on ? [...new Set([...rs, id])] : rs.filter(x => x !== id));
  const selectAll   = (on)     => setSelectedRowIds(on ? rows.map(r => r.id) : []);
  const applyFilter = (type)   => { setTypeFilter(type); setSelectedRowIds(type ? rows.filter(r => r.type === type).map(r => r.id) : []); };

  // ── Open a template for editing ─────────────────────────
  function openTemplate(tpl, sizeOverride) {
    setSelectedTpl(tpl);
    setTemplateConfig(tpl.config || { fields: [] });
    setLabelSize(sizeOverride || tpl.config?.size || '5161');
    setNamingMode(false);
    setDraftName('');
    setPreviewActive(false);
    setView('design');
  }

  // ── Close / back to template list ───────────────────────
  function closeTemplate() {
    setSelectedTpl(null);
    setTemplateConfig({ fields: [] });
    setNamingMode(false);
    setPreviewActive(false);
  }

  // ── Save ────────────────────────────────────────────────
  function startSave() {
    if (typeof selectedTpl?.id === 'number') {
      // existing – save silently
      commitSave(selectedTpl.name);
    } else {
      // new – ask for a name inline
      setDraftName('');
      setNamingMode(true);
    }
  }

  async function commitSave(name) {
    const cfg = { ...templateConfig, size: labelSize };
    if (typeof selectedTpl?.id === 'number') {
      await axios.put(`/api/label-templates/${selectedTpl.id}`, { name, config: cfg });
      const updated = { ...selectedTpl, name, config: cfg };
      setTemplates(ts => ts.map(t => t.id === selectedTpl.id ? updated : t));
      setSelectedTpl(updated);
    } else {
      const res  = await axios.post('/api/label-templates', { name, config: cfg });
      const saved = { id: res.data.id, name, config: cfg };
      setTemplates(ts => [...ts, saved]);
      setSelectedTpl(saved);
    }
    setNamingMode(false);
    setDraftName('');
  }

  // ── Template CRUD ────────────────────────────────────────
  async function handleDelete(id) {
    if (!window.confirm('Delete this template?')) return;
    await axios.delete(`/api/label-templates/${id}`);
    setTemplates(ts => ts.filter(t => t.id !== id));
    if (selectedTpl?.id === id) closeTemplate();
    setOpenMenuId(null);
  }

  async function handleDuplicate(tpl) {
    const name = `${tpl.name} copy`;
    const res  = await axios.post('/api/label-templates', { name, config: tpl.config });
    setTemplates(ts => [...ts, { id: res.data.id, name, config: tpl.config }]);
    setOpenMenuId(null);
  }

  async function handleRename(tpl) {
    const name = window.prompt('New name:', tpl.name);
    if (!name?.trim() || name === tpl.name) { setOpenMenuId(null); return; }
    await axios.put(`/api/label-templates/${tpl.id}`, { name });
    setTemplates(ts => ts.map(t => t.id === tpl.id ? { ...t, name } : t));
    if (selectedTpl?.id === tpl.id) setSelectedTpl(s => ({ ...s, name }));
    setOpenMenuId(null);
  }

  // ── Print PDF ────────────────────────────────────────────
  function handlePrint() {
    if (!selectedTpl || !selectedRows.length) return;
    try {
      const doc = generateLabelsPDF(templateConfig, selectedRows, labelSize);
      doc.save(`${selectedTpl.name || 'labels'}.pdf`);
    } catch (e) {
      alert('PDF error: ' + e.message);
    }
  }

  const canPrint = !!selectedTpl && selectedRows.length > 0;

  // ─────────────────────────────────────────────────────────
  return (
    <div className="flex h-full bg-gray-900 text-white">

      {/* ── Sidebar ─────────────────────────────────────── */}
      <aside className="w-56 bg-gray-850 border-r border-gray-700 flex flex-col h-full flex-shrink-0" style={{ backgroundColor: '#1a1f2e' }}>
        <div className="p-4 border-b border-gray-700">
          <h2 className="text-sm font-bold tracking-widest text-gray-400 uppercase mb-3">Label Creator</h2>

          <nav className="flex rounded overflow-hidden border border-gray-700">
            {['design','patch'].map(v => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`flex-1 py-1.5 text-xs font-medium capitalize transition-colors ${view === v ? 'bg-blue-700 text-white' : 'text-gray-400 hover:bg-gray-700'}`}
              >
                {v === 'design' ? 'Design' : 'Patch'}
              </button>
            ))}
          </nav>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-1">
          <p className="text-[10px] text-gray-600 uppercase tracking-widest mb-2 px-1">Saved Templates</p>

          {templates.map(tpl => (
            <div key={tpl.id} className="relative group">
              <button
                onClick={() => openTemplate(tpl)}
                className={`flex items-center w-full p-2 rounded text-left gap-2 transition-colors ${selectedTpl?.id === tpl.id ? 'bg-blue-800/50 border border-blue-700' : 'hover:bg-gray-700/50 border border-transparent'}`}
              >
                <div className="w-12 h-8 flex-shrink-0 overflow-hidden border border-gray-600 rounded bg-white">
                  <LabelPreview templateConfig={tpl.config} size={tpl.config?.size || '5161'} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate">{tpl.name}</p>
                  <p className="text-[10px] text-gray-500">{AVERY[tpl.config?.size]?.dims || tpl.config?.size || '—'}</p>
                </div>
              </button>
              <div className="absolute top-1.5 right-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={e => { e.stopPropagation(); setOpenMenuId(openMenuId === tpl.id ? null : tpl.id); }}
                  className="px-1 py-0.5 text-gray-400 hover:text-white rounded hover:bg-gray-700 text-sm leading-none"
                >⋮</button>
                {openMenuId === tpl.id && (
                  <div className="absolute right-0 mt-1 w-28 bg-gray-800 border border-gray-600 rounded shadow-xl z-10 text-xs">
                    <button onClick={() => handleRename(tpl)}    className="block w-full text-left px-3 py-2 hover:bg-gray-700">Rename</button>
                    <button onClick={() => handleDuplicate(tpl)} className="block w-full text-left px-3 py-2 hover:bg-gray-700">Duplicate</button>
                    <button onClick={() => handleDelete(tpl.id)} className="block w-full text-left px-3 py-2 text-red-400 hover:bg-red-700 hover:text-white">Delete</button>
                  </div>
                )}
              </div>
            </div>
          ))}

          {templates.length === 0 && (
            <p className="text-xs text-gray-600 italic px-1 mt-2">No saved templates yet.</p>
          )}
        </div>

        {/* Patch row count indicator */}
        {selectedRows.length > 0 && (
          <div className="p-3 border-t border-gray-700 text-xs text-gray-400">
            <span className="text-blue-400 font-medium">{selectedRows.length}</span> rows ready to print
          </div>
        )}
      </aside>

      {/* ── Main ────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col overflow-hidden">

        {/* Action bar — only when a template is open */}
        {selectedTpl && (
          <div className="flex items-center gap-3 px-4 py-2 bg-gray-800 border-b border-gray-700 flex-shrink-0">
            <button onClick={closeTemplate} className="text-gray-400 hover:text-white text-sm">← Back</button>
            <span className="text-gray-500">|</span>
            <span className="text-sm font-medium text-white truncate max-w-xs">
              {typeof selectedTpl.id === 'number' ? selectedTpl.name : 'Unsaved template'}
            </span>

            <div className="ml-auto flex items-center gap-2">
              {/* Inline name input for first save */}
              {namingMode ? (
                <div className="flex items-center gap-2">
                  <input
                    ref={nameInputRef}
                    type="text"
                    value={draftName}
                    onChange={e => setDraftName(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && draftName.trim()) commitSave(draftName.trim()); if (e.key === 'Escape') setNamingMode(false); }}
                    placeholder="Template name…"
                    className="bg-gray-700 border border-gray-500 text-white text-sm px-2 py-1 rounded outline-none focus:border-blue-500 w-44"
                  />
                  <button
                    onClick={() => draftName.trim() && commitSave(draftName.trim())}
                    disabled={!draftName.trim()}
                    className="px-3 py-1 bg-green-700 hover:bg-green-600 text-white rounded text-sm disabled:opacity-40"
                  >Save</button>
                  <button onClick={() => setNamingMode(false)} className="px-2 py-1 text-gray-400 hover:text-white text-sm">✕</button>
                </div>
              ) : (
                <button onClick={startSave} className="px-3 py-1 bg-green-700 hover:bg-green-600 text-white rounded text-sm">
                  {typeof selectedTpl.id === 'number' ? 'Save' : 'Save As…'}
                </button>
              )}

              <button
                onClick={handlePrint}
                disabled={!canPrint}
                className="px-3 py-1 bg-blue-700 hover:bg-blue-600 text-white rounded text-sm disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Print PDF {canPrint && `(${selectedRows.length})`}
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-auto">

          {/* ── Design view ─────────────────────────────── */}
          {view === 'design' && (
            selectedTpl == null ? (

              /* ── New template picker ─────────────────── */
              <div className="p-8 max-w-2xl">
                <h1 className="text-xl font-bold text-white mb-1">Create New Template</h1>
                <p className="text-gray-400 text-sm mb-6">Choose a label size to start designing.</p>

                <div className="space-y-2">
                  {SIZES.map(s => {
                    // Scale label preview box: max 64px wide, proportional height
                    const maxW = 64;
                    const previewW = Math.round(Math.min(maxW, s.labelW / 4 * maxW));
                    const previewH = Math.max(6, Math.round(s.labelH / s.labelW * previewW));
                    return (
                      <button
                        key={s.id}
                        onClick={() => openTemplate({ id: s.id, name: s.label, config: { fields: [] } }, s.id)}
                        className="w-full flex items-center gap-4 p-3 bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-blue-600 rounded-lg text-left transition-all group"
                      >
                        <div
                          className="flex-shrink-0 border-2 border-gray-600 group-hover:border-blue-500 rounded bg-white transition-colors"
                          style={{ width: previewW, height: previewH }}
                        />
                        <div>
                          <p className="font-semibold text-white text-sm">{s.label}</p>
                          <p className="text-xs text-gray-400">{s.dims} · {s.perSheet}/sheet · {s.cols}×{s.rows}</p>
                        </div>
                        <span className="ml-auto text-blue-500 text-xs opacity-0 group-hover:opacity-100 transition-opacity">Select →</span>
                      </button>
                    );
                  })}
                </div>

                {templates.length > 0 && (
                  <div className="mt-8">
                    <p className="text-xs text-gray-500 uppercase tracking-widest mb-3">Or open a saved template</p>
                    <div className="grid grid-cols-2 gap-3">
                      {templates.map(tpl => (
                        <button
                          key={tpl.id}
                          onClick={() => openTemplate(tpl)}
                          className="flex items-center gap-3 p-3 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-left transition-all"
                        >
                          <div className="w-14 h-9 flex-shrink-0 overflow-hidden border border-gray-600 rounded bg-white">
                            <LabelPreview templateConfig={tpl.config} size={tpl.config?.size || '5161'} />
                          </div>
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-white truncate">{tpl.name}</p>
                            <p className="text-xs text-gray-500">{tpl.config?.size || '—'}</p>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

            ) : (

              /* ── Designer canvas ─────────────────────── */
              <div className="flex flex-col h-full">
                <div className="flex items-center gap-3 px-4 py-2 bg-gray-800 border-b border-gray-700 flex-shrink-0">
                  <select
                    value={labelSize}
                    onChange={e => setLabelSize(e.target.value)}
                    className="bg-gray-700 text-white border border-gray-600 px-2 py-1 rounded text-sm"
                  >
                    {SIZES.map(s => (
                      <option key={s.id} value={s.id}>{s.label} – {s.dims} ({s.perSheet}/sheet)</option>
                    ))}
                  </select>

                  {selectedRows.length > 0 && (
                    <button
                      onClick={() => setPreviewActive(p => !p)}
                      className={`px-3 py-1 rounded text-sm transition-colors ${previewActive ? 'bg-amber-700 hover:bg-amber-600' : 'bg-gray-700 hover:bg-gray-600'} text-white`}
                    >
                      {previewActive ? 'Exit Preview' : `Preview with data (${selectedRows.length} rows)`}
                    </button>
                  )}

                  {previewActive && selectedRows.length > 1 && (
                    <div className="flex items-center gap-2">
                      <button onClick={() => canPrev && setPreviewIndex(i => i-1)} disabled={!canPrev} className="px-2 py-1 bg-gray-700 rounded text-sm disabled:opacity-40">◀</button>
                      <span className="text-gray-400 text-sm">{previewIndex+1} / {selectedRows.length}</span>
                      <button onClick={() => canNext && setPreviewIndex(i => i+1)} disabled={!canNext} className="px-2 py-1 bg-gray-700 rounded text-sm disabled:opacity-40">▶</button>
                    </div>
                  )}
                </div>

                <div className="flex-1 min-h-0">
                  <LabelDesigner
                    labelSize={labelSize}
                    templateConfig={templateConfig}
                    onConfigChange={setTemplateConfig}
                    previewActive={previewActive}
                    previewData={selectedRows[previewIndex] || {}}
                  />
                </div>
              </div>
            )
          )}

          {/* ── Patch view ──────────────────────────────── */}
          {view === 'patch' && (
            <div className="p-4 space-y-4">
              <h2 className="text-white font-semibold">Select rows to print</h2>

              <div className="flex flex-wrap gap-3">
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Show</label>
                  <select value={selectedShow} onChange={e => setSelectedShow(e.target.value)}
                    className="bg-gray-700 text-white border border-gray-600 p-2 rounded text-sm">
                    <option value="">Choose a show…</option>
                    {shows.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </div>
                {selectedShow && (
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Patch Sheet</label>
                    <select value={selectedPatch} onChange={e => setSelectedPatch(e.target.value)}
                      className="bg-gray-700 text-white border border-gray-600 p-2 rounded text-sm">
                      <option value="">Choose a sheet…</option>
                      {patches.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  </div>
                )}
              </div>

              {rows.length > 0 && (
                <div className="flex items-center gap-3 flex-wrap">
                  <button onClick={() => selectAll(true)}  className="px-3 py-1 bg-blue-700 hover:bg-blue-600 text-white rounded text-sm">Select All</button>
                  <button onClick={() => selectAll(false)} className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-white rounded text-sm">Deselect All</button>
                  <select value={typeFilter} onChange={e => applyFilter(e.target.value)}
                    className="bg-gray-700 text-white border border-gray-600 p-1.5 rounded text-sm">
                    <option value="">Filter by type…</option>
                    {[...new Set(rows.map(r => r.type).filter(Boolean))].map(t => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                  <span className="text-gray-400 text-sm">{selectedRowIds.length} of {rows.length} selected</span>
                </div>
              )}

              {rows.length > 0 ? (
                <div className="border border-gray-700 rounded overflow-auto" style={{ maxHeight: '60vh' }}>
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-gray-800 text-gray-400 text-xs">
                      <tr>
                        <th className="p-2 w-8">
                          <input type="checkbox"
                            checked={selectedRowIds.length === rows.length && rows.length > 0}
                            onChange={e => selectAll(e.target.checked)} />
                        </th>
                        {['Fix #','Type','Location','Universe','Address','Set'].map(h => (
                          <th key={h} className="p-2 text-left">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map(r => {
                        const checked = selectedRowIds.includes(r.id);
                        return (
                          <tr key={r.id}
                            onClick={() => toggleRow(r.id, !checked)}
                            className={`border-t border-gray-700 cursor-pointer ${checked ? 'bg-blue-900/30' : 'hover:bg-gray-800'}`}
                          >
                            <td className="p-2 text-center">
                              <input type="checkbox" checked={checked} onChange={e => { e.stopPropagation(); toggleRow(r.id, e.target.checked); }} />
                            </td>
                            <td className="p-2 font-mono text-gray-200">{r.fixture}</td>
                            <td className="p-2 text-gray-300">{r.type}</td>
                            <td className="p-2 text-gray-300">{r.location}</td>
                            <td className="p-2 text-gray-300">{r.universe}</td>
                            <td className="p-2 text-gray-300">{r.address}</td>
                            <td className="p-2 text-gray-300">{r.set}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : selectedPatch ? (
                <p className="text-gray-500 text-sm">No fixtures in this patch sheet.</p>
              ) : null}
            </div>
          )}

        </div>
      </main>
    </div>
  );
}
