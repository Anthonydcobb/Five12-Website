import React, { useState, useEffect, useRef } from 'react';
import { useParams } from 'react-router-dom';
import PatchTab from '../components/PatchTab';
import UniverseView from '../components/UniverseView';
import InsightsView from '../components/InsightsView';

function findAddressConflicts(rows) {
  const conflicts = [];
  const byUniverse = {};

  rows.forEach(r => {
    if (r.universe == null || r.address == null || r.endAddress == null) return;
    if (!byUniverse[r.universe]) byUniverse[r.universe] = [];
    byUniverse[r.universe].push(r);
  });

  Object.values(byUniverse).forEach(fixtures => {
    const sorted = [...fixtures].sort((a, b) => a.address - b.address);
    for (let i = 0; i < sorted.length; i++) {
      for (let j = i + 1; j < sorted.length; j++) {
        if (sorted[i].endAddress >= sorted[j].address) {
          conflicts.push({ fixtureA: sorted[i], fixtureB: sorted[j] });
        } else break;
      }
    }
  });

  return conflicts;
}

export default function PatchSheet() {
  const { showId, patchId } = useParams();

  const [activeTab, setActiveTab] = useState('Patch');
  const [showName, setShowName] = useState('');
  const [patchName, setPatchName] = useState('');
  const [rows, setRows] = useState([]);
  const [conflicts, setConflicts] = useState([]);

  // Dialog states
  const [overflowDialog, setOverflowDialog] = useState(null);
  const overflowResolve = useRef(null);
  const [fixtureNumError, setFixtureNumError] = useState(null);
  const [conflictError, setConflictError] = useState(null);

  const safeFetch = (url, opts) =>
    fetch(url, opts).then(res => {
      if (!res.ok) return res.text().then(t => { throw new Error(t || res.status); });
      return res.json();
    });

  useEffect(() => {
    Promise.all([
      safeFetch(`/api/shows/${showId}`),
      safeFetch(`/api/shows/${showId}/patch-sheets/${patchId}`),
      safeFetch(`/api/patch-sheets/${patchId}/rows`),
    ]).then(([show, sheet, patchRows]) => {
      setShowName(show.name);
      setPatchName(sheet.name);
      setRows(patchRows);
    }).catch(console.error);
  }, [showId, patchId]);

  useEffect(() => {
    setConflicts(findAddressConflicts(rows));
  }, [rows]);

  const updateField = (id, field, val) => {
    setRows(rs => rs.map(r => r.id === id ? { ...r, [field]: val } : r));
    safeFetch(`/api/patch-sheets/rows/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: val === '' ? null : val }),
    }).catch(console.error);
  };

  const promptOverflow = (msg) =>
    new Promise(resolve => {
      setOverflowDialog(msg);
      overflowResolve.current = resolve;
    });

  const handlePatch = async ({ fixtureNumber, fixture: fixtureObj, universe, startAddr, offset, count }) => {
    const { fixture: fixtureType, channelCount, wattage, weight, firmware, notes } = fixtureObj;
    const startFixNum = fixtureNumber !== '' ? Number(fixtureNumber) : null;
    const ch = Number(channelCount);

    // Duplicate fixture number check
    if (startFixNum !== null) {
      for (let i = 0; i < count; i++) {
        const num = String(startFixNum + i);
        const dupe = rows.find(r => String(r.fixture) === num);
        if (dupe) {
          setFixtureNumError({ fixtureType: dupe.type || fixtureType, number: num });
          return;
        }
      }
    }

    let addr = Number(startAddr);
    let univ = Number(universe);
    const newRows = [];

    for (let i = 0; i < count; i++) {
      const endAddr = addr + ch - 1;

      // Universe overflow
      if (endAddr > 512) {
        const ok = await promptOverflow(`Universe ${univ} is full.\nContinue to Universe ${univ + 1}?`);
        if (!ok) return;
        univ += 1;
        addr = 1;
      }

      // Address conflict check
      const blocking = rows.find(r =>
        Number(r.universe) === univ &&
        r.address != null &&
        r.endAddress != null &&
        !(addr + ch - 1 < r.address || addr > r.endAddress)
      );
      if (blocking) {
        setConflictError({ fixtureType, blockingFixture: blocking });
        return;
      }

      const payload = {
        fixture: startFixNum !== null ? String(startFixNum + i) : '',
        type: fixtureType,
        channelCount: ch,
        universe: univ,
        address: addr,
        endAddress: addr + ch - 1,
        wattage, weight, firmware, notes,
      };

      const row = await safeFetch(`/api/patch-sheets/${patchId}/rows`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      newRows.push(row);
      addr = addr + ch + (Number(offset) || 0);
    }

    setRows(rs => [...rs, ...newRows].sort((a, b) => {
      const af = parseFloat(a.fixture) || 0;
      const bf = parseFloat(b.fixture) || 0;
      return af - bf;
    }));
  };

  const handleRePatch = async ({ universe: initialUniv, startAddr: initialAddr, offset, selectedRows }) => {
    let curUniv = Number(initialUniv);
    let curAddr = Number(initialAddr);

    for (const id of selectedRows) {
      const row = rows.find(r => r.id === id);
      if (!row) continue;
      const ch = Number(row.channelCount) || 0;
      const endAddr = curAddr + ch - 1;

      if (endAddr > 512) {
        const ok = await promptOverflow(`Universe ${curUniv} is full.\nContinue to Universe ${curUniv + 1}?`);
        if (!ok) return;
        curUniv += 1;
        curAddr = 1;
      }

      await safeFetch(`/api/patch-sheets/rows/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ universe: curUniv, address: curAddr, endAddress: curAddr + ch - 1 }),
      });

      setRows(rs => rs.map(r => r.id === id
        ? { ...r, universe: curUniv, address: curAddr, endAddress: curAddr + ch - 1 }
        : r
      ));

      curAddr = curAddr + ch + (Number(offset) || 0);
    }
  };

  const handleUnpatch = (selectedRows) => {
    selectedRows.forEach(id => {
      ['universe', 'address', 'endAddress'].forEach(f => updateField(id, f, null));
    });
  };

  const handleRemoveFixture = (selectedRows) => {
    setRows(rs => rs.filter(r => !selectedRows.includes(r.id)));
    selectedRows.forEach(id =>
      fetch(`/api/patch-sheets/rows/${id}`, { method: 'DELETE' }).catch(console.error)
    );
  };

  const TABS = ['Patch', 'Universe View', 'Insights', 'Issues'];

  return (
    <div className="min-h-screen bg-bg text-text flex flex-col">

      {/* Universe overflow dialog */}
      {overflowDialog && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-surface border border-border rounded-lg p-6 w-80 shadow-xl">
            <h3 className="text-text font-semibold mb-2">Universe Full</h3>
            <p className="text-text text-sm mb-5 whitespace-pre-line">{overflowDialog}</p>
            <div className="flex justify-end gap-3">
              <button onClick={() => { setOverflowDialog(null); overflowResolve.current?.(false); }} className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm text-text">Cancel</button>
              <button onClick={() => { setOverflowDialog(null); overflowResolve.current?.(true); }} className="px-4 py-2 bg-brand hover:bg-brand-hi rounded text-sm text-text">Continue</button>
            </div>
          </div>
        </div>
      )}

      {/* Fixture number error dialog */}
      {fixtureNumError && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-surface border border-brand rounded-lg p-6 w-96 shadow-xl">
            <h3 className="text-brand-hi font-semibold mb-3">Fixture Number Conflict</h3>
            <p className="text-text text-sm mb-3">Fixture numbers must be unique.</p>
            <div className="bg-bg rounded p-3 text-sm mb-5 space-y-1">
              <div className="text-text-muted">Fixture Type: <span className="text-text">{fixtureNumError.fixtureType}</span></div>
              <div className="text-text-muted">Duplicate Number: <span className="text-brand-hi font-mono font-bold">{fixtureNumError.number}</span></div>
            </div>
            <div className="flex justify-end">
              <button onClick={() => setFixtureNumError(null)} className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm text-text">OK</button>
            </div>
          </div>
        </div>
      )}

      {/* Address conflict error dialog */}
      {conflictError && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-surface border border-brand rounded-lg p-6 w-96 shadow-xl">
            <h3 className="text-brand-hi font-semibold mb-3">Address Conflict</h3>
            <p className="text-text text-sm mb-3">
              <span className="text-text font-medium">{conflictError.fixtureType}</span> cannot be patched here. The following fixture is in the way:
            </p>
            <div className="bg-bg rounded p-3 text-sm mb-5 space-y-1">
              <div className="text-text-muted">Fix #: <span className="text-text font-mono">{conflictError.blockingFixture.fixture}</span></div>
              <div className="text-text-muted">Fixture: <span className="text-text">{conflictError.blockingFixture.type}</span></div>
              <div className="text-text-muted">Addresses: <span className="text-text">{conflictError.blockingFixture.address}–{conflictError.blockingFixture.endAddress}</span></div>
            </div>
            <div className="flex justify-end">
              <button onClick={() => setConflictError(null)} className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm text-text">OK</button>
            </div>
          </div>
        </div>
      )}

      {/* Page header */}
      <div className="px-6 pt-5 pb-0 border-b border-border">
        <div className="text-xs text-text-muted uppercase tracking-wider mb-3">
          {showName} / {patchName}
        </div>
        <div className="flex gap-1">
          {TABS.map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm rounded-t-md transition-colors relative ${
                activeTab === tab
                  ? 'bg-surface text-text font-medium'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              {tab}
              {tab === 'Issues' && conflicts.length > 0 && (
                <span className="ml-1.5 bg-brand text-text text-xs px-1.5 py-0.5 rounded-full font-mono">
                  {conflicts.length}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 bg-surface p-6">
        {activeTab === 'Patch' && (
          <PatchTab
            patchId={patchId}
            rows={rows}
            conflicts={conflicts}
            onPatch={handlePatch}
            onRePatch={handleRePatch}
            onUnpatch={handleUnpatch}
            onRemoveFixture={handleRemoveFixture}
            updateField={updateField}
          />
        )}
        {activeTab === 'Universe View' && (
          <UniverseView rows={rows} conflicts={conflicts} />
        )}
        {activeTab === 'Insights' && (
          <InsightsView rows={rows} />
        )}
        {activeTab === 'Issues' && (
          <div>
            <h2 className="text-base font-semibold text-brand-hi mb-4">
              Address Conflicts {conflicts.length > 0 && `(${conflicts.length})`}
            </h2>
            {conflicts.length === 0 ? (
              <p className="text-online text-sm">No conflicts detected.</p>
            ) : (
              <ul className="space-y-2">
                {conflicts.map((c, i) => (
                  <li key={i} className="bg-brand-dim/40 border border-brand/50 px-4 py-3 rounded text-sm text-text">
                    <span className="font-medium text-text">Universe {c.fixtureA.universe}: </span>
                    Fix #{c.fixtureA.fixture} ({c.fixtureA.type}) at {c.fixtureA.address}–{c.fixtureA.endAddress}
                    {' '}overlaps Fix #{c.fixtureB.fixture} ({c.fixtureB.type}) at {c.fixtureB.address}–{c.fixtureB.endAddress}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
