// File: src/pages/PatchSheet.jsx
import React, { useState, useEffect } from 'react';
import { useParams }        from 'react-router-dom';
import PatchTab             from '../components/PatchTab';
import UniverseView         from '../components/UniverseView';
import InsightsView         from '../components/InsightsView';

export default function PatchSheet() {
  const { showId, patchId } = useParams();

  // ─── Tab State
  const [activeTab, setActiveTab] = useState('Patch');
  const TABS = ['Patch','Universe View','Insights'];

  // ─── Data State
  const [showName,  setShowName ]  = useState('');
  const [patchName, setPatchName] = useState('');
  const [rows,      setRows]      = useState([]);
  const [fixtures,  setFixtures]  = useState([]);

  // ─── JSON helper
  const safeFetchJson = (url, opts) =>
    fetch(url, opts).then(res => {
      if (!res.ok) return res.text().then(txt => { throw new Error(txt || res.status); });
      return res.json();
    });

  // ─── Load breadcrumbs & data
  useEffect(() => {
    safeFetchJson(`/api/shows/${showId}`)
      .then(d => setShowName(d.name))
      .catch(console.error);
  }, [showId]);

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

  // ─── Field‐update helper
  const updateField = (id, field, val) => {
    setRows(rs => rs.map(r => r.id === id ? { ...r, [field]: val } : r));
    const payload = val === '' ? null : val;
    safeFetchJson(`/api/patch-sheets/rows/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: payload })
    }).catch(console.error);
  };

  // ─── 1) PATCH: add new fixtures
  const handlePatch = ({
    fixtureNumber, fixture: fixtureObj,
    universe, startAddr, offset, count
  }) => {
    const {
      fixture: fixtureType, mode,
      channelCount, location,
      notes, wattage, weight, firmware
    } = fixtureObj;

    let addr = Number(startAddr);
    const promises = [];

    for (let i = 0; i < count; i++) {
      const payload = {
        fixture: fixtureNumber !== '' ? Number(fixtureNumber) + i : '',
        type: fixtureType, mode, channelCount,
        universe, address: addr,
        endAddress: addr + channelCount - 1,
        location, notes, wattage, weight, firmware
      };
      promises.push(
        safeFetchJson(`/api/patch-sheets/${patchId}/rows`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        })
      );
      addr = addr + channelCount + (Number(offset) || 0);
    }

    Promise.all(promises)
      .then(newRows => {
        setRows(rs => [...rs, ...newRows].sort((a,b) => Number(a.fixture) - Number(b.fixture)));
      })
      .catch(console.error);
  };

  // ─── 2) RE-PATCH: re-assign addresses
  const handleRePatch = ({ universe: initialUniv, startAddr: initialAddr, offset, selectedRows }) => {
    let curUniv = Number(initialUniv);
    let curAddr  = Number(initialAddr);
    const ids     = Array.from(new Set(selectedRows));
    let idx = 0;

    const processNext = () => {
      if (idx >= ids.length) return;
      const id = ids[idx];
      const row = rows.find(r => r.id === id);
      const ch  = Number(row.channelCount);
      const end = curAddr + ch - 1;

      if (end > 512) {
        // confirm overflow…
        // (you can wire this into your overflowDialog logic)
        curUniv += 1;
        curAddr  = 1;
        return processNext();
      }

      safeFetchJson(`/api/patch-sheets/rows/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ universe: curUniv, address: curAddr, endAddress: end })
      })
      .then(() => {
        // locally update
        updateField(id, 'universe', curUniv);
        updateField(id, 'address', curAddr);
        updateField(id, 'endAddress', end);
        curAddr = end + 1 + (Number(offset) || 0);
        idx++;
        processNext();
      })
      .catch(console.error);
    };

    processNext();
  };

  // ─── 3) UNPATCH: null out universe/address
  const handleUnpatch = selectedRows => {
    selectedRows.forEach(id => {
      ['universe','address','endAddress'].forEach(f => updateField(id, f, null));
    });
  };

  // ─── 4) REMOVE FIXTURE
  const handleRemoveFixture = selectedRows => {
    // Optimistically remove from UI…
    setRows(rs => rs.filter(r => !selectedRows.includes(r.id)));
    // …and delete on server
    selectedRows.forEach(id =>
      fetch(`/api/patch-sheets/rows/${id}`, { method: 'DELETE' }).catch(console.error)
    );
  };

  return (
    <div className="p-6 bg-gray-900 text-white min-h-screen">
      {/* breadcrumb */}
      <div className="text-sm text-gray-400 mb-4">
        {showName} &gt; {patchName}
      </div>

      {/* tabs */}
      <div className="flex space-x-4 border-b border-gray-700 mb-6">
        {TABS.map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`pb-2 ${
              activeTab===tab
                ? 'border-b-2 border-blue-400 text-white'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* panels */}
      {activeTab==='Patch' && (
        <PatchTab
          rows={rows}
          fixtures={fixtures}
          onPatch={handlePatch}
          onRePatch={handleRePatch}
          onUnpatch={handleUnpatch}
          onRemoveFixture={handleRemoveFixture}
          updateField={updateField}
        />
      )}
      {activeTab==='Universe View' && <UniverseView rows={rows} />}
      {activeTab==='Insights'      && <InsightsView rows={rows} fixtures={fixtures} />}
    </div>
  );
}
