// File: src/pages/PatchSheet.jsx
import React, { useState, useEffect, useRef } from 'react';
import { useParams } from 'react-router-dom';
import PatchModal from '../components/PatchModal';

export default function PatchSheet() {
  const { showId, patchId } = useParams();

  // ─── State
  const [patchName, setPatchName] = useState('');
  const [rows, setRows] = useState([]);
  const [fixtures, setFixtures] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [isRePatchMode, setIsRePatchMode] = useState(false);
  const [selectedCells, setSelectedCells] = useState(new Set());
  const [isDragging, setIsDragging] = useState(false);
  const [command, setCommand] = useState('');
  const [overflowDialog, setOverflowDialog] = useState(null);
  const overflowCallback = useRef(null);
  const tableRef = useRef(null);

  const cols = [
    'set', 'fixture', 'type', 'mode', 'channelCount',
    'universe', 'address', 'endAddress', 'location',
    'notes', 'wattage', 'weight', 'firmware'
  ];
  const cellKey = (id, field) => `${id}::${field}`;

  // ─── Helpers
  const anyFullRowSelected = rows.some(r =>
    cols.every(f => selectedCells.has(cellKey(r.id, f)))
  );
  const safeFetchJson = (url, opts) =>
    fetch(url, opts).then(res => {
      if (!res.ok) {
        return res.text().then(txt => {
          console.error('Server error:', res.status, txt);
          throw new Error(`Server returned ${res.status}`);
        });
      }
      return res.json();
    });

  // ─── Load Data
  useEffect(() => {
    safeFetchJson(`/api/shows/${showId}/patch-sheets/${patchId}`)
      .then(d => setPatchName(d.name))
      .catch(console.error);
  }, [showId, patchId]);

  useEffect(() => {
    safeFetchJson(`/api/patch-sheets/${patchId}/rows`)
      .then(setRows)
      .catch(console.error);
  }, [patchId]);

  useEffect(() => {
    safeFetchJson('/api/fixtures')
      .then(setFixtures)
      .catch(console.error);
  }, []);

  // ─── Overflow Dialog
  const showOverflowConfirm = (msg, cb) => {
    setOverflowDialog(msg);
    overflowCallback.current = cb;
  };
  const handleOverflow = ok => {
    const cb = overflowCallback.current;
    setOverflowDialog(null);
    overflowCallback.current = null;
    if (cb) cb(ok);
  };

  // ─── Click‐outside to clear selection ───────────────────────────────────────
  useEffect(() => {
    const onDown = e => {
      // Don’t clear while the modal is open
      if (showModal) return;

      if (tableRef.current && !tableRef.current.contains(e.target)) {
        setSelectedCells(new Set());
      }
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [showModal]);

  useEffect(() => {
    const onUp = () => setIsDragging(false);
    window.addEventListener('mouseup', onUp);
    return () => window.removeEventListener('mouseup', onUp);
  }, []);

  const onCellMouseDown = (id, field) => {
    setSelectedCells(new Set([cellKey(id, field)]));
    setIsDragging(true);
  };
  const onCellMouseEnter = (id, field) => {
    if (!isDragging) return;
    setSelectedCells(prev => new Set(prev).add(cellKey(id, field)));
  };

  const toggleRow = id => {
    const rowKeys = cols.map(f => cellKey(id, f));
    setSelectedCells(prev => {
      const nxt = new Set(prev);
      const allSel = rowKeys.every(k => nxt.has(k));
      rowKeys.forEach(k => allSel ? nxt.delete(k) : nxt.add(k));
      return nxt;
    });
  };

  // ─── Field Updates

  const updateField = (id, field, val) => {
    // keep local state in sync
    setRows(rs => rs.map(r => r.id === id ? { ...r, [field]: val } : r));

    // coerce '' → null for integer columns
    const payloadVal =
      val === '' ? null : val;

    safeFetchJson(`/api/patch-sheets/rows/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: payloadVal })
    }).catch(console.error);
  };
  const updateSelectedFields = val => {
    selectedCells.forEach(key => {
      const [id, field] = key.split('::');
      updateField(Number(id), field, val);
    });
  };
  const updateFixtureFields = input => {
    const keys = [...selectedCells].filter(k => k.endsWith('::fixture'));
    if (!keys.length) return;
    const ids = keys.map(k => Number(k.split('::')[0]));
    const assigns = [];
    if (input === '') {
      ids.forEach(id => updateField(id, 'fixture', ''));
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

  // ─── Patch / Repatch / Unpatch / Remove
  const openPatch = () => { setIsRePatchMode(false); setShowModal(true); };
  const openRePatch = () => { setIsRePatchMode(true); setShowModal(true); };

  // File: src/pages/PatchSheet.jsx
  const handlePatch = ({
    fixtureNumber,       // may be '' if no start‐fix was entered
    fixture: fixtureObj,
    universe,
    startAddr,
    offset,
    count
  }) => {
    const {
      fixture: fixtureType,
      mode,
      channelCount,
      location,
      notes,
      wattage,
      weight,
      firmware
    } = fixtureObj;

    let addr = Number(startAddr);
    const newRows = [];

    for (let i = 0; i < count; i++) {
      // if user typed a start fixture, increment by i; otherwise leave blank
      const fixtureNum = fixtureNumber !== '' ? Number(fixtureNumber) + i : '';

      // compute this fixture’s end address
      const end = addr + channelCount - 1;

      const payload = {
        fixture: fixtureNum,
        type: fixtureType,
        mode,
        channelCount,
        universe,
        address: addr,
        endAddress: end,
        location,
        notes,
        wattage,
        weight,
        firmware
      };

      // fire off the POST
      newRows.push(
        safeFetchJson(`/api/patch-sheets/${patchId}/rows`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        })
      );

      // advance addr: last end +1 + any extra offset
      addr = end + 1 + (Number(offset) || 0);
    }

    // wait for all, then append in order
    Promise.all(newRows)
      .then(results => {
        setRows(rs =>
          [...rs, ...results].sort(
            (a, b) => Number(a.fixture) - Number(b.fixture)
          )
        );
      })
      .catch(console.error);

    setShowModal(false);
    setSelectedCells(new Set());
  };




// File: src/pages/PatchSheet.jsx

// … earlier in the file …

const handleRePatch = ({ universe: initialUniv, startAddr: initialAddr, offset, selectedRows }) => {
  // Sort & dedupe the IDs, but preserve the order the modal gave you
  const ids = Array.from(new Set(selectedRows));

  let curUniv = Number(initialUniv);
  let curAddr = Number(initialAddr);
  let idx     = 0;

  // A recursive helper to process one row at a time
  function processNext() {
    // If we’ve run out of rows, finalize
    if (idx >= ids.length) {
      // close dialog & clear selection
      setShowModal(false);
      setIsRePatchMode(false);
      setSelectedCells(new Set());
      // reload to be sure
      safeFetchJson(`/api/patch-sheets/${patchId}/rows`)
        .then(fresh => setRows(fresh))
        .catch(console.error);
      return;
    }

    const id   = ids[idx];
    const row  = rows.find(r => r.id === id);
    const ch   = Number(row.channelCount);
    const end  = curAddr + ch - 1;

    // If this fixture would overflow channel 512 of the current universe...
    if (end > 512) {
      showOverflowConfirm(
        `Universe ${curUniv} is full (would need channels ${curAddr}–${end}).\nPatch next universe?`,
        ok => {
          if (ok) {
            // bump universe & reset address, then retry this same row
            curUniv += 1;
            curAddr = 1;
            processNext();
          } else {
            // user said “stop here” → finalize without touching the rest
            setShowModal(false);
            setIsRePatchMode(false);
            setSelectedCells(new Set());
            // finally reload
            safeFetchJson(`/api/patch-sheets/${patchId}/rows`)
              .then(fresh => setRows(fresh))
              .catch(console.error);
          }
        }
      );
      return;
    }

    // Otherwise, we can patch this row
    const payload = {
      universe:   curUniv,
      address:    curAddr,
      endAddress: end
    };

    // Fire the PUT
    safeFetchJson(`/api/patch-sheets/rows/${id}`, {
      method:  'PUT',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload)
    })
    .then(() => {
      // Optimistically update local state
      setRows(rs =>
        rs.map(r =>
          r.id === id
            ? { ...r, universe: curUniv, address: curAddr, endAddress: end }
            : r
        )
      );
      // Advance address: end + 1, then your extra offset
      curAddr = end + 1 + (Number(offset) || 0);
      idx += 1;
      // Continue with the next row
      processNext();
    })
    .catch(err => {
      console.error(`Failed to re-patch row ${id}`, err);
      // You might want to stop on error or skip to next
      processNext();
    });
  }

  // Kick off the sequence
  processNext();
};













  const handleUnpatch = () => {
    const full = rows
      .filter(r => cols.every(f => selectedCells.has(cellKey(r.id, f))))
      .map(r => r.id);

    full.forEach(id =>
      ['universe', 'address', 'endAddress'].forEach(field =>
        updateField(id, field, null)    // ← now sends JSON null
      )
    );

    setSelectedCells(new Set());
  };

  const handleRemoveFixture = () => {
    const ids = new Set([...selectedCells].map(k => Number(k.split('::')[0])));
    ids.forEach(id => fetch(`/api/patch-sheets/rows/${id}`, { method: 'DELETE' }).catch(console.error));
    setRows(rs => rs.filter(r => !ids.has(r.id)));
    setSelectedCells(new Set());
  };

  // ─── Command‐Line Selection
  const handleCommandKey = e => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const cmd = command.trim();
    const ids = new Set();
    if (/^\d+\.\d+$/.test(cmd)) rows.forEach(r => r.fixture === cmd && ids.add(r.id));
    else if (/^(\d+)\s*[<>]\s*(\d+)$/.test(cmd)) {
      const [_, a, b] = cmd.match(/^(\d+)\s*[<>]\s*(\d+)$/);
      const [min, max] = [Number(a), Number(b)].sort((x, y) => x - y);
      rows.forEach(r => {
        const m = Math.floor(Number(r.fixture));
        if (m >= min && m <= max) ids.add(r.id);
      });
    } else if (/^(\d+)\s*\+\s*(\d+)$/.test(cmd)) {
      const [_, a, b] = cmd.match(/^(\d+)\s*\+\s*(\d+)$/);
      rows.forEach(r => {
        const m = Math.floor(Number(r.fixture));
        if (m === Number(a) || m === Number(b)) ids.add(r.id);
      });
    } else if (/^\d+$/.test(cmd)) rows.forEach(r => Math.floor(Number(r.fixture)) === Number(cmd) && ids.add(r.id));
    const sel = new Set();
    ids.forEach(id => cols.forEach(f => sel.add(cellKey(id, f))));
    setSelectedCells(sel);
    setCommand('');
  };

  // ─── Render
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
      <header className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">{patchName}</h1>
        <div className="flex items-start space-x-2">
          <textarea
            value={command}
            onChange={e => setCommand(e.target.value)}
            onKeyDown={handleCommandKey}
            onMouseDown={e => e.stopPropagation()}
            placeholder="Command line"
            className="bg-gray-700 text-white p-2 rounded w-48 h-12"
          />
          <button onMouseDown={e => e.stopPropagation()} onClick={openPatch} className="px-4 py-2 bg-green-600 rounded">Patch</button>
          <button onMouseDown={e => e.stopPropagation()} onClick={handleUnpatch} disabled={!anyFullRowSelected} className="px-4 py-2 bg-red-600 rounded disabled:opacity-50">Unpatch</button>
          <button onMouseDown={e => e.stopPropagation()} onClick={openRePatch} disabled={!anyFullRowSelected} className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50">Re-Patch</button>
          <button onMouseDown={e => e.stopPropagation()} onClick={handleRemoveFixture} disabled={!anyFullRowSelected} className="px-4 py-2 bg-red-800 rounded disabled:opacity-50">Remove Fixture</button>
        </div>
      </header>
      <div ref={tableRef} className="overflow-auto bg-gray-800 rounded">
        <table className="min-w-full table-auto">
          <thead>
            <tr className="bg-gray-700">
              <th className="px-2 py-2"></th>
              {['Set', 'Fixture #', 'Fixture Type', 'Mode', 'Ch. Count', 'Universe', 'Address', 'End Address', 'Location', 'Notes', 'Wattage', 'Weight', 'Firmware'].map((h, i) => <th key={i} className="px-4 py-2 border text-left">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const rowKeys = cols.map(f => cellKey(r.id, f)); const rowSel = rowKeys.every(k => selectedCells.has(k)); return (
                <tr key={r.id} className={rowSel ? 'bg-blue-600' : (r.id % 2 === 0 ? 'bg-gray-800' : 'bg-gray-700')}>
                  <td className="px-2 py-2 border">
                    <button onClick={e => { e.stopPropagation(); toggleRow(r.id); }} className="w-4 h-4 bg-gray-500 hover:bg-gray-600 rounded" />
                  </td>
                  {cols.map(field => {
                    const key = cellKey(r.id, field); const sel = selectedCells.has(key); return (
                      <td key={field} onMouseDown={() => onCellMouseDown(r.id, field)} onMouseEnter={() => onCellMouseEnter(r.id, field)} className={`px-4 py-2 border ${sel ? 'bg-blue-600' : ''}`}>
                        {['set', 'location', 'notes', 'fixture'].includes(field) ? (
                          <input
                            type="text"
                            value={r[field] || ''}
                            onChange={e => { const v = e.target.value; setRows(rs => rs.map(x => x.id === r.id ? { ...x, [field]: v } : x)); }}
                            onBlur={e => { const v = e.target.value.trim(); if (field === 'fixture') { const keys = [...selectedCells].filter(k => k.endsWith('::fixture')); keys.length > 1 ? updateFixtureFields(v) : updateField(r.id, 'fixture', v); } else updateSelectedFields(v); }}
                            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); const v = e.target.value.trim(); if (field === 'fixture') { const keys = [...selectedCells].filter(k => k.endsWith('::fixture')); keys.length > 1 ? updateFixtureFields(v) : updateField(r.id, 'fixture', v); } else updateSelectedFields(v); } }}
                            className="w-full bg-transparent focus:outline-none text-white"
                          />
                        ) : r[field]}
                      </td>
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
          onPatch={isRePatchMode ? handleRePatch : handlePatch}
          isRePatch={isRePatchMode}
          selectedRows={[...new Set([...selectedCells].map(k => Number(k.split('::')[0])))]}
          onClose={() => { setShowModal(false); setIsRePatchMode(false); setSelectedCells(new Set()); }}
        />
      )}
    </div>
  );
}
