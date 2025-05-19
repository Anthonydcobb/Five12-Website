// File: src/components/PatchTab.jsx
import React, { useState, useEffect, useRef } from 'react';
import PatchModal from './PatchModal';

export default function PatchTab({
    rows,
    fixtures,
    updateField,
    onPatch,
    onRePatch,
    onUnpatch,
    onRemoveFixture
}) {
    // ─── Local UI state
    const [showModal, setShowModal] = useState(false);
    const [isRePatchMode, setIsRePatchMode] = useState(false);
    const [selectedCells, setSelectedCells] = useState(new Set());
    const [isDragging, setIsDragging] = useState(false);
    const [command, setCommand] = useState('');
    const commandRef = useRef(null);
    const [overflowDialog, setOverflowDialog] = useState(null);
    const overflowCallback = useRef(null);
    const tableRef = useRef(null);

    // ─── Color-By settings
    const [colorBy, setColorBy] = useState('');
    const palette = ['#F87171', '#60A5FA', '#34D399', '#FBBF24', '#A78BFA'];
    const cols = [
        'set', 'fixture', 'type', 'mode', 'channelCount',
        'universe', 'address', 'endAddress', 'location',
        'notes', 'wattage', 'weight', 'firmware'
    ];

    // derive colors
    const colorValues = colorBy ? Array.from(new Set(rows.map(r => r[colorBy]))) : [];
    const colorMap = colorValues.reduce((acc, v, i) => { acc[v] = palette[i % palette.length]; return acc; }, {});

    // helper to build cell key
    const cellKey = (id, field) => `${id}::${field}`;

    // compute selected row IDs
    const selectedRowIds = Array.from(
        new Set([...selectedCells].map(key => Number(key.split('::')[0])))
    );

    const updateSelectedFields = (field, val) => {
        const keys = [...selectedCells].filter(k => k.endsWith(`::${field}`));
        const ids = keys.map(k => Number(k.split('::')[0]));
        ids.forEach(id => updateField(id, field, val));
    };

    const updateFixtureFields = input => {
        const keys = [...selectedCells].filter(k => k.endsWith('::fixture'));
        if (!keys.length) return;
        const ids = keys.map(k => Number(k.split('::')[0]));
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
            for (let i = 0; i < ids.length; i++) assigns.push(String(start + i));
        }
        ids.forEach((id, i) => updateField(id, 'fixture', assigns[i]));
    };

    // ─── Global key for typing into command line
    useEffect(() => {
        const handleGlobalKey = e => {
            if (document.activeElement === commandRef.current) return;
            if (selectedCells.size === 0 && e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                const char = e.key === 'x' ? '>' : e.key;
                const el = commandRef.current;
                const { selectionStart, selectionEnd } = el;
                const updated = command.slice(0, selectionStart) + char + command.slice(selectionEnd);
                setCommand(updated);
                setTimeout(() => el.setSelectionRange(selectionStart + 1, selectionStart + 1), 0);
                el.focus();
            }
        };
        window.addEventListener('keydown', handleGlobalKey);
        return () => window.removeEventListener('keydown', handleGlobalKey);
    }, [selectedCells, command]);

    // ─── Escape clears selection
    useEffect(() => {
        const clearOnEsc = e => { if (e.key === 'Escape') setSelectedCells(new Set()); };
        window.addEventListener('keydown', clearOnEsc);
        return () => window.removeEventListener('keydown', clearOnEsc);
    }, []);

    // ─── Drag end & click-outside
    useEffect(() => {
        const onUp = () => setIsDragging(false);
        window.addEventListener('mouseup', onUp);
        return () => window.removeEventListener('mouseup', onUp);
    }, []);

    useEffect(() => {
        const onDown = e => {
            if (showModal) return;
            if (tableRef.current && !tableRef.current.contains(e.target)) {
                setSelectedCells(new Set());
            }
        };
        document.addEventListener('mousedown', onDown);
        return () => document.removeEventListener('mousedown', onDown);
    }, [showModal]);

    // ─── Cell selection
    const onCellMouseDown = (id, field) => {
        setSelectedCells(new Set([cellKey(id, field)]));
        setIsDragging(true);
    };
    const onCellMouseEnter = (id, field) => {
        if (!isDragging) return;
        setSelectedCells(prev => new Set(prev).add(cellKey(id, field)));
    };
    const toggleRow = id => {
        const keys = cols.map(f => cellKey(id, f));
        setSelectedCells(prev => {
            const nxt = new Set(prev);
            const all = keys.every(k => nxt.has(k));
            keys.forEach(k => all ? nxt.delete(k) : nxt.add(k));
            return nxt;
        });
    };

    // ─── Command-line parsing
    const handleCommandKey = e => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        const cmd = command.trim();
        const ids = new Set();

        // open-ended: "101 >"
        const openMatch = cmd.match(/^(\d+)\s*[<>]\s*$/);
        if (openMatch) {
            let cur = Number(openMatch[1]);
            const map = new Map();
            rows.forEach(r => {
                const n = Math.floor(Number(r.fixture));
                if (!map.has(n)) map.set(n, []);
                map.get(n).push(r.id);
            });
            while (map.has(cur)) { map.get(cur).forEach(id => ids.add(id)); cur++; }
        }
        // exact 101.1
        else if (/^\d+\.\d+$/.test(cmd)) {
            rows.forEach(r => r.fixture === cmd && ids.add(r.id));
        }
        // closed range 101 > 105
        else if (/^(\d+)\s*[<>]\s*(\d+)$/.test(cmd)) {
            const [, a, b] = cmd.match(/^(\d+)\s*[<>]\s*(\d+)$/);
            const [min, max] = [Number(a), Number(b)].sort((x, y) => x - y);
            rows.forEach(r => {
                const m = Math.floor(Number(r.fixture));
                if (m >= min && m <= max) ids.add(r.id);
            });
        }
        // single number 101
        else if (/^\d+$/.test(cmd)) {
            const n = Number(cmd);
            rows.forEach(r => Math.floor(Number(r.fixture)) === n && ids.add(r.id));
        }

        const sel = new Set();
        ids.forEach(id => cols.forEach(f => sel.add(cellKey(id, f))));
        setSelectedCells(sel);
        setCommand('');
    };

    // ─── Overflow confirm
    const showOverflow = (msg, cb) => { setOverflowDialog(msg); overflowCallback.current = cb; };
    const handleOverflow = ok => { const cb = overflowCallback.current; setOverflowDialog(null); overflowCallback.current = null; if (cb) cb(ok); };

    // ─── Local handlers
    const handleUnpatchClick = () => onUnpatch(selectedRowIds);
    const handleRemoveClick = () => { onRemoveFixture(selectedRowIds); setSelectedCells(new Set()); };

    return (
        <div className="p-6 bg-gray-900 text-white min-h-screen relative">
            {overflowDialog && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center">
                    <div className="bg-gray-800 p-6 rounded-lg w-80">
                        <p className="text-white mb-4">{overflowDialog}</p>
                        <div className="flex justify-end space-x-2">
                            <button onClick={() => handleOverflow(true)} className="px-4 py-2 bg-green-600 rounded">Continue</button>
                            <button onClick={() => handleOverflow(false)} className="px-4 py-2 bg-red-600 rounded">Cancel</button>
                        </div>
                    </div>
                </div>
            )}

            <header className="flex items-center space-x-4 mb-6">
                <textarea
                    ref={commandRef}
                    value={command}
                    onChange={e => setCommand(e.target.value)}
                    onKeyDown={e => {
                        if (e.key === 'x' && !e.ctrlKey && !e.metaKey) {
                            e.preventDefault();
                            const el = commandRef.current;
                            const { selectionStart, selectionEnd } = el;
                            const updated = command.slice(0, selectionStart) + '>' + command.slice(selectionEnd);
                            setCommand(updated);
                            setTimeout(() => el.setSelectionRange(selectionStart + 1, selectionStart + 1), 0);
                        } else {
                            handleCommandKey(e);
                        }
                    }}
                    placeholder="Command line"
                    className="w-64 bg-gray-800 text-white p-2 rounded"
                />
                <button onMouseDown={e => e.stopPropagation()} onClick={() => { setIsRePatchMode(false); setShowModal(true); }} className="px-4 py-2 bg-green-600 rounded">Patch</button>
                <button onMouseDown={e => e.stopPropagation()} onClick={handleUnpatchClick} disabled={!selectedRowIds.length} className="px-4 py-2 bg-red-600 rounded disabled:opacity-50">Unpatch</button>
                <button onMouseDown={e => e.stopPropagation()} onClick={() => { setIsRePatchMode(true); setShowModal(true); }} disabled={!selectedRowIds.length} className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50">Re-Patch</button>
                <button onMouseDown={e => e.stopPropagation()} onClick={handleRemoveClick} disabled={!selectedRowIds.length} className="px-4 py-2 bg-red-800 rounded disabled:opacity-50">Remove Fixture</button>
                <label className="flex items-center space-x-1 text-white">
                    <span>Color By:</span>
                    <select value={colorBy} onChange={e => setColorBy(e.target.value)} className="bg-gray-800 text-white p-1 rounded">
                        <option value="">None</option>
                        <option value="type">Fixture Type</option>
                        <option value="universe">Universe</option>
                        <option value="location">Location</option>
                    </select>
                </label>
                {colorBy && (
                    <div className="flex flex-wrap space-x-2">
                        {colorValues.map(v => (
                            <span key={v} style={{ backgroundColor: colorMap[v] }} className="px-2 py-1 rounded text-sm text-white">{v}</span>
                        ))}
                    </div>
                )}
            </header>

            <div ref={tableRef} className="overflow-auto bg-gray-800 rounded">
                <table className="min-w-full table-auto">
                    <thead>
                        <tr className="bg-gray-700">
                            <th className="px-2 py-2"></th>
                            {cols.map((f, i) => <th key={i} className="px-4 py-2 border text-left">{f}</th>)}
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map(r => {
                            const rowKeys = cols.map(f => cellKey(r.id, f));
                            const rowSel = rowKeys.every(k => selectedCells.has(k));
                            const bgStyle = colorBy ? { backgroundColor: colorMap[r[colorBy]] } : {};
                            return (
                                <tr key={r.id} className={rowSel ? 'bg-blue-600' : ''} style={bgStyle}>
                                    <td className="px-2 py-2 border">
                                        <button onClick={e => { e.stopPropagation(); toggleRow(r.id); }} className="w-4 h-4 bg-gray-500 hover:bg-gray-600 rounded" />
                                    </td>
                                    {cols.map(field => {
                                        const key = cellKey(r.id, field);
                                        const sel = selectedCells.has(key);
                                        return (
                                            <td key={field} onMouseDown={() => onCellMouseDown(r.id, field)} onMouseEnter={() => onCellMouseEnter(r.id, field)} className={`px-4 py-2 border ${sel ? 'bg-blue-600' : ''}`}>{
                                                ['set', 'location', 'notes', 'fixture'].includes(field) ? (
                                                    <input
                                                        type="text"
                                                        value={r[field] || ''}
                                                        onChange={e => {
                                                            const value = e.target.value;
                                                            updateField(r.id, field, value);
                                                        }}
                                                        onBlur={e => {
                                                            const v = e.target.value.trim();
                                                            if (field === 'fixture') {
                                                                selectedCells.size > 1 ? updateFixtureFields(v) : updateField(r.id, 'fixture', v);
                                                            } else if (selectedCells.size > 1) {
                                                                updateSelectedFields(field, v);
                                                            } else {
                                                                updateField(r.id, field, v);
                                                            }
                                                        }}
                                                        onKeyDown={e => {
                                                            if (e.key === 'Enter') {
                                                                e.preventDefault();
                                                                const v = e.target.value.trim();
                                                                if (field === 'fixture') {
                                                                    selectedCells.size > 1 ? updateFixtureFields(v) : updateField(r.id, 'fixture', v);
                                                                } else if (selectedCells.size > 1) {
                                                                    updateSelectedFields(field, v);
                                                                } else {
                                                                    updateField(r.id, field, v);
                                                                }
                                                            }
                                                        }}
                                                        className="w-full bg-transparent focus:outline-none text-white"
                                                    />

                                                ) : r[field]
                                            }</td>
                                        );
                                    })}
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>

            {showModal && (
                <PatchModal
                    fixtures={fixtures}
                    onPatch={isRePatchMode ? onRePatch : onPatch}
                    onRePatch={onRePatch} // ✅ add this
                    isRePatch={isRePatchMode}
                    selectedRows={selectedRowIds}
                    onClose={() => { setShowModal(false); setIsRePatchMode(false); }}
                />
            )}
        </div>
    );
}
