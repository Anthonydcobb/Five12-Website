// File: src/components/PatchModal.jsx
import React, { useState, useEffect } from 'react';

export default function PatchModal({
  fixtures,
  onPatch,
  isRePatch,
  selectedRows,
  onClose
}) {
  const [search, setSearch] = useState('');
  const [filtered, setFiltered] = useState([]);
  const [selectedFixture, setSelectedFixture] = useState(null);
  const [startFix, setStartFix] = useState('');   // optional
  const [count, setCount] = useState(1);
  const [universe, setUniverse] = useState('1');
  const [startAddr, setStartAddr] = useState('1');
  const [offset, setOffset] = useState(0);

  // Filter fixtures if this is the initial Patch
  useEffect(() => {
    if (!isRePatch) {
      const term = search.trim().toLowerCase();
      setFiltered(fixtures.filter(f =>
        f.fixture.toLowerCase().includes(term)
      ));
    }
  }, [search, fixtures, isRePatch]);

  // When Re-Patch, force count to match selected rows
  useEffect(() => {
    if (isRePatch) setCount(selectedRows.length);
  }, [isRePatch, selectedRows]);

  const handleSubmit = () => {
    if (isRePatch) {
      onPatch({
        universe,
        startAddr,
        offset,
        selectedRows
      });
    } else {
      if (!selectedFixture) return;
      onPatch({
        fixture:        selectedFixture,
        fixtureNumber:  startFix,    // may be blank
        count,
        universe,
        startAddr,
        offset
      });
    }
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-gray-900 text-white p-6 rounded-lg shadow-xl w-3/4 max-w-xl">
        <h2 className="text-2xl font-medium mb-4">
          {isRePatch ? 'Re-Patch Fixtures' : 'Patch Fixtures'}
        </h2>

        {!isRePatch ? (
          <>
            {/* Search */}
            <label className="block mb-2">
              <span className="text-sm">Search Fixture</span>
              <div className="flex">
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  className="flex-1 px-2 py-1 bg-gray-800 border border-gray-700 rounded-l text-white focus:outline-none"
                />
                <button
                  onClick={() => setSearch('')}
                  className="px-2 bg-gray-700 rounded-r text-white"
                >
                  ×
                </button>
              </div>
            </label>
            <div className="mb-4 h-32 overflow-auto bg-gray-800 rounded">
              <ul>
                {filtered.map(f => (
                  <li
                    key={f.id}
                    className={`p-1 cursor-pointer ${selectedFixture?.id === f.id ? 'bg-blue-600' : ''}`}
                    onClick={() => setSelectedFixture(f)}
                  >
                    {f.fixture} | {f.mode} | {f.channelCount} ch | {f.notes}
                  </li>
                ))}
              </ul>
            </div>

            {/* Start Fix & Count */}
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block mb-1">Start Fix #</label>
                <input
                  type="text"
                  value={startFix}
                  onChange={e => setStartFix(e.target.value)}
                  className="w-full px-2 py-1 bg-gray-800 border border-gray-700 rounded text-white focus:outline-none"
                />
              </div>
              <div>
                <label className="block mb-1">Count</label>
                <input
                  type="number"
                  value={count}
                  onChange={e => setCount(Number(e.target.value))}
                  min="1"
                  className="w-full px-2 py-1 bg-gray-800 border border-gray-700 rounded text-white focus:outline-none"
                />
              </div>
            </div>
          </>
        ) : (
          /* Re-Patch UI: just row count */
          <div className="mb-4">
            <span className="text-sm">Rows Selected</span>
            <input
              type="number"
              value={count}
              disabled
              className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded p-2 text-white"
            />
          </div>
        )}

        {/* Universe / Start Addr / Offset */}
        <div className="grid grid-cols-3 gap-3 mb-6">
          <label>
            <span className="text-sm">Universe</span>
            <input
              type="number"
              value={universe}
              onChange={e => setUniverse(e.target.value)}
              className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded p-2 text-white focus:outline-none"
            />
          </label>
          <label>
            <span className="text-sm">Start Addr</span>
            <input
              type="number"
              value={startAddr}
              onChange={e => setStartAddr(e.target.value)}
              className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded p-2 text-white focus:outline-none"
            />
          </label>
          <label>
            <span className="text-sm">Offset</span>
            <input
              type="number"
              value={offset}
              onChange={e => setOffset(Number(e.target.value))}
              className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded p-2 text-white focus:outline-none"
            />
          </label>
        </div>

        {/* Actions */}
        <div className="flex justify-end space-x-3">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-700 rounded hover:bg-gray-600 text-white"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!isRePatch && !selectedFixture}
            className="px-4 py-2 bg-blue-600 rounded hover:bg-blue-500 text-white disabled:opacity-50"
          >
            {isRePatch ? 'Apply' : 'Patch'}
          </button>
        </div>
      </div>
    </div>
);
}
