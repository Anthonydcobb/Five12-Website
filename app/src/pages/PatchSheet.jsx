// File: src/pages/PatchSheet.jsx
import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import PatchTab from '../components/PatchTab';
import UniverseView from '../components/UniverseView';
import InsightsView from '../components/InsightsView';

export default function PatchSheet() {
  // ─── Address Conflict Detection
  function findAddressConflicts(rows) {
    const conflicts = [];

    // Group rows by universe
    const universeMap = {};
    rows.forEach(r => {
      if (!universeMap[r.universe]) universeMap[r.universe] = [];
      universeMap[r.universe].push(r);
    });

    // Check each universe for overlap
    Object.entries(universeMap).forEach(([univ, fixtures]) => {
      fixtures.sort((a, b) => a.address - b.address);
      for (let i = 0; i < fixtures.length; i++) {
        const a = fixtures[i];
        for (let j = i + 1; j < fixtures.length; j++) {
          const b = fixtures[j];
          if (a.endAddress >= b.address) {
            conflicts.push({
              universe: univ,
              fixtureA: a,
              fixtureB: b
            });
          } else {
            break;
          }
        }
      }
    });

    return conflicts;
  }

  function getUniverseUsageBySet(rows) {
    const data = {};
  
    rows.forEach(row => {
      const setName = row.set || 'Unassigned';
      const univ = row.universe;
      const chCount = Number(row.channelCount) || 0;
  
      if (!data[setName]) {
        data[setName] = {
          universes: new Set(),
          channelTotal: 0,
          fixtures: 0
        };
      }
  
      data[setName].universes.add(univ);
      data[setName].channelTotal += chCount;
      data[setName].fixtures += 1;
    });
  
    Object.keys(data).forEach(set => {
      data[set].universes = Array.from(data[set].universes).filter(Boolean).sort();
    });
  
    return data;
  }
  

  function findFixtureReuseAcrossSheets(rows, currentPatchId) {
    const usageMap = {}; // fixtureNumber → [patchSheetId, ...]
  
    rows.forEach(row => {
      const fixture = row.fixture?.toString().trim();
      const patchId = row.patchSheetId;
      if (!fixture) return;
  
      if (!usageMap[fixture]) usageMap[fixture] = new Set();
      usageMap[fixture].add(patchId);
    });
  
    // Return fixtures used in multiple sheets (not just current)
    const reused = Object.entries(usageMap)
      .filter(([, patchIds]) => patchIds.size > 1)
      .map(([fixture, patchIds]) => ({
        fixture,
        patchSheetIds: Array.from(patchIds).map(Number),
        isUsedHere: patchIds.has(Number(currentPatchId))
      }));
  
    return reused;
  }
  






  // ─── Channel Usage Calculation
  function getChannelUsageByUniverse(rows) {
    const usage = {};

    rows.forEach(row => {
      const chCount = row.channelCount || 0;
      const univ = row.universe;
      if (!usage[univ]) usage[univ] = 0;
      usage[univ] += chCount;
    });

    return usage;
  }

  function getFixtureTypeCounts(rows) {
    const counts = {};
    rows.forEach(row => {
      const type = row.type || 'Unknown';
      counts[type] = (counts[type] || 0) + 1;
    });
    return counts;
  }





  const { showId, patchId } = useParams();

  // ─── Tab State
  const [activeTab, setActiveTab] = useState('Patch');
  const TABS = ['Patch', 'Universe View', 'Insights', 'Issues'];

  // ─── Data State
  const [showName, setShowName] = useState('');
  const [patchName, setPatchName] = useState('');
  const [rows, setRows] = useState([]);
  const [fixtures, setFixtures] = useState([]);
  const [conflicts, setConflicts] = useState([]);
  const [channelUsage, setChannelUsage] = useState({});
  const [fixtureTypeCounts, setFixtureTypeCounts] = useState({});
  const [universeByLocation, setUniverseByLocation] = useState({});
  const [universeBySet, setUniverseBySet] = useState({});
  const [allSheetRows, setAllSheetRows] = useState([]);
  const [fixtureReuse, setFixtureReuse] = useState([]);





  // ─── JSON helper
  const safeFetchJson = (url, opts) =>
    fetch(url, opts).then(res => {
      if (!res.ok) return res.text().then(txt => { throw new Error(txt || res.status); });
      return res.json();
    });

    function getUniverseUsageByLocation(rows) {
      const data = {};
    
      rows.forEach(row => {
        const location = row.location || 'Unassigned';
        const univ = row.universe;
        const chCount = Number(row.channelCount) || 0;
    
        if (!data[location]) {
          data[location] = {
            universes: new Set(),
            channelTotal: 0,
            fixtures: 0
          };
        }
    
        data[location].universes.add(univ);
        data[location].channelTotal += chCount;
        data[location].fixtures += 1;
      });
    
      // Convert Sets to arrays for easier rendering
      Object.keys(data).forEach(loc => {
        data[loc].universes = Array.from(data[loc].universes).filter(Boolean).sort();
      });
    
      return data;
    }
    





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
    setConflicts(findAddressConflicts(rows));
    setChannelUsage(getChannelUsageByUniverse(rows));
    setFixtureTypeCounts(getFixtureTypeCounts(rows)); // ✅ NEW
  }, [rows]);

  useEffect(() => {
    safeFetchJson('/api/fixtures')
      .then(setFixtures)
      .catch(console.error);
  }, []);

  useEffect(() => {
    setConflicts(findAddressConflicts(rows));
    setChannelUsage(getChannelUsageByUniverse(rows));
    setFixtureTypeCounts(getFixtureTypeCounts(rows));
    setUniverseByLocation(getUniverseUsageByLocation(rows)); // ✅ NEW
    setUniverseBySet(getUniverseUsageBySet(rows)); // ✅ new
  }, [rows]);

  useEffect(() => {
    safeFetchJson(`/api/shows/${showId}/patch-sheets/all-rows`)
      .then(setAllSheetRows)
      .catch(console.error);
  }, [showId]);
  
  useEffect(() => {
    if (allSheetRows.length > 0) {
      setFixtureReuse(findFixtureReuseAcrossSheets(allSheetRows, patchId));
    }
  }, [allSheetRows, patchId]);
  
  


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
        setRows(rs => [...rs, ...newRows].sort((a, b) => Number(a.fixture) - Number(b.fixture)));
      })
      .catch(console.error);
  };

  // ─── 2) RE-PATCH: re-assign addresses
  const handleRePatch = ({ universe: initialUniv, startAddr: initialAddr, offset, selectedRows }) => {
    let curUniv = Number(initialUniv);
    let curAddr = Number(initialAddr);
    const ids = Array.from(new Set(selectedRows));
    let idx = 0;

    const processNext = () => {
      if (idx >= ids.length) return;
      const id = ids[idx];
      const row = rows.find(r => r.id === id);
      const ch = Number(row.channelCount);
      const end = curAddr + ch - 1;

      if (end > 512) {
        // confirm overflow…
        // (you can wire this into your overflowDialog logic)
        curUniv += 1;
        curAddr = 1;
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
      ['universe', 'address', 'endAddress'].forEach(f => updateField(id, f, null));
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
            className={`pb-2 ${activeTab === tab
              ? 'border-b-2 border-blue-400 text-white'
              : 'text-gray-400 hover:text-white'
              }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* panels */}
      {activeTab === 'Patch' && (
        <PatchTab
          patchId={patchId} // ✅ pass patchId down
          rows={rows}
          fixtures={fixtures}
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
        <InsightsView
          rows={rows}
          fixtures={fixtures}
          channelUsage={channelUsage}
          fixtureTypeCounts={fixtureTypeCounts} // ✅ add this
          universeByLocation={universeByLocation} // ✅ NEW
          universeBySet={universeBySet} // ✅ add this
          fixtureReuse={fixtureReuse} // ✅
          patchName={patchName}
        />
      )}


      {activeTab === 'Issues' && (
        <div className="p-4">
          <h2 className="text-xl mb-4 text-red-400">Address Conflicts</h2>
          {conflicts.length === 0 ? (
            <p className="text-green-400">✅ No conflicts found.</p>
          ) : (
            <ul className="space-y-2">
              {conflicts.map((c, i) => (
                <li key={i} className="bg-red-900 p-2 rounded text-white text-sm">
                  <strong>Universe {c.universe}:</strong> Fixture #{c.fixtureA.fixture} ({c.fixtureA.address}-{c.fixtureA.endAddress})
                  overlaps with Fixture #{c.fixtureB.fixture} ({c.fixtureB.address}-{c.fixtureB.endAddress})
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

    </div>
  );
}
