// File: src/components/PatchModal.jsx
import React, { useState, useEffect, useRef } from 'react';

export default function PatchModal({
  fixtures,
  onPatch,
  onRePatch,
  isRePatch,
  selectedRows,
  onClose
}) {
  const [search, setSearch] = useState('');
  const [filtered, setFiltered] = useState([]);
  const [selectedFixture, setSelectedFixture] = useState(null);
  const [startFix, setStartFix] = useState('');
  const [count, setCount] = useState(isRePatch ? selectedRows.length : 1);
  const [universe, setUniverse] = useState('1');
  const [startAddr, setStartAddr] = useState('1');
  const [offset, setOffset] = useState('0');

  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!isRePatch) {
      const term = search.trim().toLowerCase();
      setFiltered(
        fixtures.filter(f => f.fixture.toLowerCase().includes(term))
      );
    }
  }, [search, fixtures, isRePatch]);

  useEffect(() => {
    if (isRePatch) {
      setCount(selectedRows.length);
    }
  }, [isRePatch, selectedRows]);

  const handleSubmit = () => {
    if (isRePatch) {
      onRePatch({ universe, startAddr, offset, selectedRows });
    } else {
      if (!selectedFixture) return;
      onPatch({
        fixture: selectedFixture,
        fixtureNumber: startFix,
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
      <div
        className="bg-bg text-white p-6 rounded-lg shadow-xl w-3/4 max-w-xl"
        onClick={e => e.stopPropagation()}
        onKeyDown={e => e.stopPropagation()}
        tabIndex={0}
      >
        <h2 className="text-2xl font-medium mb-4">
          {isRePatch ? 'Re-Patch Fixtures' : 'Patch Fixtures'}
        </h2>

        {!isRePatch ? (
          <>
            <label className="block mb-2">
              <span className="text-sm">Search Fixture</span>
              <div className="flex mt-1">
                <input
                  ref={inputRef}
                  type="text"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  className="flex-1 px-2 py-1 bg-surface border border-border rounded-l text-white focus:outline-none"
                  placeholder="Type fixture name..."
                />
                <button
                  onClick={() => setSearch('')}
                  className="px-2 bg-surface-2 rounded-r text-white"
                >
                  ×
                </button>
              </div>
            </label>
            <div className="mb-4 h-32 overflow-auto bg-surface rounded">
              <ul>
                {filtered.map(f => (
                  <li
                    key={f.id}
                    className={`p-1 cursor-pointer ${selectedFixture?.id === f.id ? 'bg-brand' : ''}`}
                    onClick={() => setSelectedFixture(f)}
                  >
                    {f.fixture} || {f.channelCount} ch | {f.notes}
                  </li>
                ))}
              </ul>
            </div>

            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block mb-1">Start Fix #</label>
                <input
                  type="text"
                  value={startFix}
                  onChange={e => setStartFix(e.target.value)}
                  className="w-full px-2 py-1 bg-surface border border-border rounded text-white"
                  placeholder="e.g. 101"
                />
              </div>
              <div>
                <label className="block mb-1">Count</label>
                <input
                  type="number"
                  value={count}
                  onChange={e => setCount(Number(e.target.value))}
                  min="1"
                  className="w-full px-2 py-1 bg-surface border border-border rounded text-white"
                />
              </div>
            </div>
          </>
        ) : (
          <div className="mb-4">
            <span className="text-sm">Rows Selected</span>
            <input
              type="number"
              value={count}
              disabled
              className="mt-1 block w-full bg-surface border border-border rounded p-2 text-white"
            />
          </div>
        )}

        <div className="grid grid-cols-3 gap-3 mb-6">
          <label>
            <span className="text-sm">Universe</span>
            <input
              type="number"
              value={universe}
              onChange={e => setUniverse(e.target.value)}
              className="mt-1 block w-full bg-surface border border-border rounded p-2 text-white"
            />
          </label>
          <label>
            <span className="text-sm">Start Addr</span>
            <input
              type="number"
              value={startAddr}
              onChange={e => setStartAddr(e.target.value)}
              className="mt-1 block w-full bg-surface border border-border rounded p-2 text-white"
            />
          </label>
          <label>
            <span className="text-sm">Offset</span>
            <input
              type="number"
              value={offset}
              onChange={e => setOffset(e.target.value)}
              className="mt-1 block w-full bg-surface border border-border rounded p-2 text-white"
            />
          </label>
        </div>

        <div className="flex justify-end space-x-3">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-surface-2 rounded hover:bg-border text-white"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!isRePatch && !selectedFixture}
            className="px-4 py-2 bg-brand rounded hover:bg-brand text-white disabled:opacity-50"
          >
            {isRePatch ? 'Apply' : 'Patch'}
          </button>
        </div>
      </div>
    </div>
  );
}