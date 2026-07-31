import React, { useState, useEffect, useRef, useMemo } from 'react';
import PatchForm from './PatchForm';
import RepatchForm from './RepatchForm';
import ImportWizard from './ImportWizard';
import DymoPrintDialog from './DymoPrintDialog';

const COLS = [
  { key: 'set',          label: 'Set',          editable: true,  sortable: true  },
  { key: 'fixture',      label: 'Fix #',         editable: true,  sortable: true  },
  { key: 'universe',     label: 'Universe',      editable: false, sortable: true  },
  { key: 'address',      label: 'Address',       editable: false, sortable: true  },
  { key: 'endAddress',   label: 'End Addr',      editable: false, sortable: false },
  { key: 'type',         label: 'Fixture Type',  editable: false, sortable: true  },
  { key: 'channelCount', label: 'CH Count',      editable: false, sortable: false },
  { key: 'location',     label: 'Location',      editable: true,  sortable: true  },
  { key: 'wattage',      label: 'Wattage',       editable: true,  sortable: false },
  { key: 'weight',       label: 'Weight',        editable: true,  sortable: false },
  { key: 'firmware',     label: 'Firmware',      editable: true,  sortable: false },
  { key: 'notes',        label: 'Notes',         editable: true,  sortable: false },
];

const ALL_KEYS = COLS.map(c => c.key);
const cellKey = (id, field) => `${id}::${field}`;

export default function PatchTab({
  patchId,
  rows,
  conflicts,
  onPatch,
  onRePatch,
  onUnpatch,
  onRemoveFixture,
  updateField,
}) {
  const [showPatchForm, setShowPatchForm] = useState(false);
  const [showRepatchForm, setShowRepatchForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [showDymo, setShowDymo] = useState(false);
  const [selectedCells, setSelectedCells] = useState(new Set());
  const [isDragging, setIsDragging] = useState(false);
  const [command, setCommand] = useState('');
  const [sortConfig, setSortConfig] = useState({ key: null, direction: null });
  const [colorBy, setColorBy] = useState('');

  const commandRef = useRef(null);
  const tableRef = useRef(null);
  const importButtonRef = useRef(null);

  const closeImport = () => {
    setShowImport(false);
    setTimeout(() => importButtonRef.current?.focus(), 0);
  };

  const selectedRowIds = useMemo(() =>
    Array.from(new Set([...selectedCells].map(k => Number(k.split('::')[0])))),
    [selectedCells]
  );

  const sortedRows = useMemo(() => {
    if (!sortConfig.key) return rows;
    const sorted = [...rows].sort((a, b) => {
      const va = a[sortConfig.key] ?? '';
      const vb = b[sortConfig.key] ?? '';
      return String(va).localeCompare(String(vb), undefined, { numeric: true });
    });
    return sortConfig.direction === 'desc' ? sorted.reverse() : sorted;
  }, [rows, sortConfig]);

  // Dark, saturated tones for "color by" so light cell text stays legible.
  const palette = ['#3b5b8c', '#3d6b52', '#8c6d3b', '#7a4a6b', '#4a4a8c', '#3d6b6b', '#8c4a4a'];
  const colorValues = colorBy ? [...new Set(rows.map(r => r[colorBy]))] : [];
  const colorMap = colorValues.reduce((acc, v, i) => ({ ...acc, [v]: palette[i % palette.length] }), {});

  const conflictIds = useMemo(() => {
    const ids = new Set();
    conflicts.forEach(c => { ids.add(c.fixtureA.id); ids.add(c.fixtureB.id); });
    return ids;
  }, [conflicts]);

  // ─── Cell selection
  const onCellMouseDown = (id, field) => {
    setSelectedCells(new Set([cellKey(id, field)]));
    setIsDragging(true);
  };
  const onCellMouseEnter = (id, field) => {
    if (!isDragging) return;
    setSelectedCells(prev => new Set([...prev, cellKey(id, field)]));
  };
  const toggleRow = (id) => {
    const keys = ALL_KEYS.map(f => cellKey(id, f));
    setSelectedCells(prev => {
      const next = new Set(prev);
      const allSel = keys.every(k => next.has(k));
      keys.forEach(k => allSel ? next.delete(k) : next.add(k));
      return next;
    });
  };

  // ─── Multi-cell update
  const updateSelectedField = (field, val) => {
    const ids = [...selectedCells]
      .filter(k => k.endsWith(`::${field}`))
      .map(k => Number(k.split('::')[0]));
    ids.forEach(id => updateField(id, field, val));
  };

  const updateFixtureNumbers = (input) => {
    const ids = [...selectedCells]
      .filter(k => k.endsWith('::fixture'))
      .map(k => Number(k.split('::')[0]));
    if (!ids.length) return;
    const assigns = [];
    if (input === '') {
      ids.forEach(() => assigns.push(''));
    } else if (input.includes('/')) {
      let [maj, min] = input.split('/')[0].split('.').map(Number);
      const minMax = Number(input.split('/')[1]);
      for (let i = 0; i < ids.length; i++) {
        assigns.push(`${maj}.${min}`);
        min++;
        if (min > minMax) { maj++; min = 1; }
      }
    } else {
      let start = Number(input);
      ids.forEach((_, i) => assigns.push(String(start + i)));
    }
    ids.forEach((id, i) => updateField(id, 'fixture', assigns[i]));
  };

  // ─── Command line
  const handleCommand = (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const cmd = command.trim();
    const ids = new Set();

    if (/^(\d+)\s*[<>]\s*$/.test(cmd)) {
      let cur = Number(cmd.match(/^(\d+)/)[1]);
      const map = new Map();
      rows.forEach(r => {
        const n = Math.floor(Number(r.fixture));
        if (!map.has(n)) map.set(n, []);
        map.get(n).push(r.id);
      });
      while (map.has(cur)) { map.get(cur).forEach(id => ids.add(id)); cur++; }
    } else if (/^\d+\.\d+$/.test(cmd)) {
      rows.forEach(r => r.fixture === cmd && ids.add(r.id));
    } else if (/^(\d+)\s*[<>]\s*(\d+)$/.test(cmd)) {
      const [, a, b] = cmd.match(/^(\d+)\s*[<>]\s*(\d+)$/);
      const [min, max] = [Number(a), Number(b)].sort((x, y) => x - y);
      rows.forEach(r => {
        const n = Math.floor(Number(r.fixture));
        if (n >= min && n <= max) ids.add(r.id);
      });
    } else if (/^\d+$/.test(cmd)) {
      const n = Number(cmd);
      rows.forEach(r => Math.floor(Number(r.fixture)) === n && ids.add(r.id));
    }

    const sel = new Set();
    ids.forEach(id => ALL_KEYS.forEach(f => sel.add(cellKey(id, f))));
    setSelectedCells(sel);
    setCommand('');
  };

  // ─── Global keyboard
  useEffect(() => {
    const onKey = e => {
      const tag = document.activeElement?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      if (e.key === 'Escape') { setSelectedCells(new Set()); return; }
      if (selectedCells.size === 0 && e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        setCommand(prev => prev + (e.key === 'x' ? '>' : e.key));
        commandRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedCells]);

  useEffect(() => {
    const onUp = () => setIsDragging(false);
    window.addEventListener('mouseup', onUp);
    return () => window.removeEventListener('mouseup', onUp);
  }, []);

  useEffect(() => {
    const onDown = e => {
      if (showPatchForm || showRepatchForm) return;
      if (tableRef.current && !tableRef.current.contains(e.target)) {
        setSelectedCells(new Set());
      }
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [showPatchForm, showRepatchForm]);

  const handleSort = (key) => {
    setSortConfig(prev => ({
      key,
      direction: prev.key === key
        ? prev.direction === 'asc' ? 'desc' : prev.direction === 'desc' ? null : 'asc'
        : 'asc',
    }));
  };

  const handleExport = () => {
    window.open(`/api/patch-sheets/${patchId}/export-excel`, '_blank');
  };

  return (
    <div className="flex flex-col gap-4">

      {/* Toolbar */}
      <div className="flex items-center gap-3 flex-wrap">
        <input
          ref={commandRef}
          type="text"
          value={command}
          onChange={e => setCommand(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'x' && !e.ctrlKey && !e.metaKey) {
              e.preventDefault();
              setCommand(prev => prev + '>');
            } else {
              handleCommand(e);
            }
          }}
          placeholder="101 > 105  or  201"
          className="w-48 px-3 py-1.5 bg-surface-2 border border-border text-text text-sm rounded placeholder-text-muted focus:outline-none focus:border-brand font-mono"
        />

        <div className="flex items-center gap-2">
          <button
            onMouseDown={e => e.stopPropagation()}
            onClick={() => setShowPatchForm(true)}
            className="px-3 py-1.5 bg-online hover:brightness-110 text-bg text-sm rounded font-medium"
          >
            Patch
          </button>
          <button
            onMouseDown={e => e.stopPropagation()}
            onClick={() => setShowRepatchForm(true)}
            disabled={!selectedRowIds.length}
            className="px-3 py-1.5 bg-gel hover:brightness-110 text-bg text-sm rounded font-medium disabled:opacity-40"
          >
            Re-Patch
          </button>
          <button
            onMouseDown={e => e.stopPropagation()}
            onClick={() => onUnpatch(selectedRowIds)}
            disabled={!selectedRowIds.length}
            className="px-3 py-1.5 bg-warn hover:brightness-110 text-bg text-sm rounded font-medium disabled:opacity-40"
          >
            Unpatch
          </button>
          <button
            onMouseDown={e => e.stopPropagation()}
            onClick={() => { onRemoveFixture(selectedRowIds); setSelectedCells(new Set()); }}
            disabled={!selectedRowIds.length}
            className="px-3 py-1.5 bg-brand hover:bg-brand-hi text-white text-sm rounded font-medium disabled:opacity-40"
          >
            Remove
          </button>
        </div>

        {selectedRowIds.length > 0 && (
          <span className="text-text-muted text-sm">{selectedRowIds.length} selected</span>
        )}

        <div className="ml-auto flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-text">
            Color by
            <select
              value={colorBy}
              onChange={e => setColorBy(e.target.value)}
              className="bg-surface-2 border border-border text-text text-sm rounded px-2 py-1 focus:outline-none"
            >
              <option value="">None</option>
              <option value="type">Fixture Type</option>
              <option value="universe">Universe</option>
              <option value="location">Location</option>
            </select>
          </label>

          <button
            ref={importButtonRef}
            onClick={() => setShowImport(true)}
            className="px-3 py-1.5 bg-surface-2 hover:bg-border border border-border text-text text-sm rounded"
          >
            Import
          </button>
          <button onClick={handleExport} className="px-3 py-1.5 bg-surface-2 hover:bg-border border border-border text-text text-sm rounded">
            Export
          </button>
          <button onClick={() => setShowDymo(true)}
            className="px-3 py-1.5 bg-surface-2 hover:bg-border border border-border text-text text-sm rounded">
            Labels
          </button>
        </div>
      </div>

      {/* Color legend */}
      {colorBy && colorValues.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {colorValues.map(v => (
            <span key={v} style={{ backgroundColor: colorMap[v] }} className="px-2 py-0.5 rounded text-xs text-text font-medium">
              {v || 'Unset'}
            </span>
          ))}
        </div>
      )}

      {/* Table */}
      <div ref={tableRef} className="overflow-auto rounded border border-border shadow">
        <table className="min-w-full text-sm border-collapse">
          <thead>
            <tr className="bg-surface-2 text-text sticky top-0">
              <th className="w-9 px-2 py-2 border-b border-border" />
              {COLS.map(col => (
                <th
                  key={col.key}
                  onClick={() => col.sortable && handleSort(col.key)}
                  className={`px-3 py-2 border-b border-border text-left whitespace-nowrap text-xs font-semibold uppercase tracking-wide ${
                    col.sortable ? 'cursor-pointer hover:bg-border select-none' : ''
                  }`}
                >
                  {col.label}
                  {sortConfig.key === col.key && sortConfig.direction && (
                    <span className="ml-1 text-gel">
                      {sortConfig.direction === 'asc' ? '▲' : '▼'}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((r, idx) => {
              const rowKeys = ALL_KEYS.map(f => cellKey(r.id, f));
              const rowSelected = rowKeys.every(k => selectedCells.has(k));
              const hasConflict = conflictIds.has(r.id);
              const bgColor = colorBy ? colorMap[r[colorBy]] : null;

              let rowClass = idx % 2 === 0 ? 'bg-surface' : 'bg-surface-2';
              if (rowSelected) rowClass = 'bg-gel/15';
              else if (hasConflict) rowClass = 'bg-brand-dim/50';
              else if (bgColor) rowClass = '';

              return (
                <tr
                  key={r.id}
                  className={`border-b border-border ${rowClass}`}
                  style={bgColor && !rowSelected && !hasConflict ? { backgroundColor: bgColor } : {}}
                >
                  <td className="px-2 py-1 border-r border-border text-center">
                    <button
                      onClick={e => { e.stopPropagation(); toggleRow(r.id); }}
                      className={`w-4 h-4 rounded border flex items-center justify-center mx-auto text-xs ${
                        rowSelected ? 'bg-gel border-gel text-bg' : 'border-border hover:border-muted'
                      }`}
                    >
                      {rowSelected && '✓'}
                    </button>
                  </td>
                  {COLS.map(col => {
                    const key = cellKey(r.id, col.key);
                    const cellSel = selectedCells.has(key);
                    return (
                      <td
                        key={col.key}
                        onMouseDown={() => onCellMouseDown(r.id, col.key)}
                        onMouseEnter={() => onCellMouseEnter(r.id, col.key)}
                        className={`px-3 py-1 border-r border-border text-text ${
                          cellSel ? 'bg-gel/25 outline outline-1 outline-gel' : ''
                        }`}
                      >
                        {col.editable ? (
                          <input
                            type="text"
                            value={r[col.key] ?? ''}
                            onChange={e => updateField(r.id, col.key, e.target.value)}
                            onBlur={e => {
                              const v = e.target.value.trim();
                              if (col.key === 'fixture' && selectedCells.size > 1) {
                                updateFixtureNumbers(v);
                              } else if (selectedCells.size > 1) {
                                updateSelectedField(col.key, v);
                              } else {
                                updateField(r.id, col.key, v);
                              }
                            }}
                            onKeyDown={e => {
                              if (e.key === 'Enter') {
                                const v = e.target.value.trim();
                                if (col.key === 'fixture' && selectedCells.size > 1) {
                                  updateFixtureNumbers(v);
                                } else if (selectedCells.size > 1) {
                                  updateSelectedField(col.key, v);
                                } else {
                                  updateField(r.id, col.key, v);
                                }
                                e.target.blur();
                              }
                            }}
                            className="w-full bg-transparent focus:outline-none text-text min-w-0"
                          />
                        ) : (
                          <span className="block select-none text-text">
                            {r[col.key] ?? ''}
                            {col.key === 'type' && r.importedFixtureType && (
                              <span className="block text-[10px] text-text-muted whitespace-nowrap"
                                title="Original patch-sheet fixture identity">
                                Imported: {r.importedFixtureType} · {r.importedChannelCount ?? '?'}ch
                              </span>
                            )}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={COLS.length + 1} className="px-4 py-10 text-center text-text-muted bg-surface">
                  No fixtures patched yet. Click <span className="text-online font-medium">Patch</span> to add fixtures.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {showPatchForm && (
        <PatchForm
          onPatch={onPatch}
          onClose={() => setShowPatchForm(false)}
        />
      )}
      {showRepatchForm && (
        <RepatchForm
          selectedRows={selectedRowIds}
          rows={rows}
          onRePatch={onRePatch}
          onClose={() => setShowRepatchForm(false)}
        />
      )}
      {showImport && (
        <ImportWizard
          patchId={patchId}
          onClose={closeImport}
          onImported={(result) => {
            setShowImport(false);
            const inserted = typeof result === 'number' ? result : result.inserted;
            const details = typeof result === 'number' ? ''
              : ` (${result.matchedRows || 0} matched, ${result.unmatchedRows || 0} unmatched)`;
            alert(`Imported ${inserted} rows${details}`);
            window.location.reload();
          }}
        />
      )}
      {showDymo && (
        <DymoPrintDialog
          patchRows={rows}
          selectedRows={rows.filter(r => selectedRowIds.includes(r.id))}
          onClose={() => setShowDymo(false)}
        />
      )}
    </div>
  );
}
