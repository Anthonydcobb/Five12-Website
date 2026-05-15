import React, { useState, useRef } from 'react';

export default function RepatchForm({ selectedRows, rows, onRePatch, onClose }) {
  const [universe, setUniverse] = useState('1');
  const [startAddr, setStartAddr] = useState('1');
  const [offset, setOffset] = useState('0');
  const univRef = useRef(null);

  const selectedFixtures = selectedRows
    .map(id => rows.find(r => r.id === id))
    .filter(Boolean);

  const handleSubmit = () => {
    onRePatch({ universe, startAddr, offset, selectedRows });
    onClose();
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleSubmit();
    if (e.key === 'Escape') onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-gray-900 text-white rounded-lg shadow-2xl w-full max-w-md p-6"
        onClick={e => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="flex justify-between items-center mb-5">
          <h2 className="text-lg font-semibold">Re-Patch Fixtures</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-2xl leading-none w-8 h-8 flex items-center justify-center">×</button>
        </div>

        {/* Selected fixtures preview */}
        <div className="mb-5">
          <label className="block text-xs text-gray-400 mb-2 uppercase tracking-wide">
            Selected — {selectedFixtures.length} fixture{selectedFixtures.length !== 1 ? 's' : ''}
          </label>
          <div className="bg-gray-800 border border-gray-700 rounded max-h-36 overflow-auto">
            {selectedFixtures.map(r => (
              <div key={r.id} className="px-3 py-2 text-sm border-b border-gray-700 last:border-0 flex justify-between items-center">
                <span className="text-gray-300">
                  Fix #{r.fixture || '—'} <span className="text-gray-500 text-xs ml-1">{r.type}</span>
                </span>
                <span className="text-gray-500 text-xs font-mono">{r.channelCount} ch</span>
              </div>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 mb-6">
          <div>
            <label className="block text-xs text-gray-400 mb-1 uppercase tracking-wide">Universe</label>
            <input
              ref={univRef}
              type="number"
              value={universe}
              onChange={e => setUniverse(e.target.value)}
              min="1"
              autoFocus
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white text-sm focus:outline-none focus:border-blue-400"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1 uppercase tracking-wide">Start Address</label>
            <input
              type="number"
              value={startAddr}
              onChange={e => setStartAddr(e.target.value)}
              min="1"
              max="512"
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white text-sm focus:outline-none focus:border-blue-400"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1 uppercase tracking-wide">Offset</label>
            <input
              type="number"
              value={offset}
              onChange={e => setOffset(e.target.value)}
              min="0"
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white text-sm focus:outline-none focus:border-blue-400"
            />
          </div>
        </div>

        <div className="flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm text-white">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium text-white"
          >
            Apply Re-Patch
          </button>
        </div>
      </div>
    </div>
  );
}
