import React, { useState, useEffect, useRef } from 'react';

export default function PatchForm({ fixtures, onPatch, onClose }) {
  const [search, setSearch] = useState('');
  const [filtered, setFiltered] = useState(fixtures);
  const [selected, setSelected] = useState(null);
  const [hovered, setHovered] = useState(null);
  const [startFix, setStartFix] = useState('');
  const [count, setCount] = useState(1);
  const [universe, setUniverse] = useState('1');
  const [startAddr, setStartAddr] = useState('1');
  const [offset, setOffset] = useState('0');
  const searchRef = useRef(null);

  useEffect(() => { searchRef.current?.focus(); }, []);

  useEffect(() => {
    const term = search.trim().toLowerCase();
    setFiltered(fixtures.filter(f => f.fixture.toLowerCase().includes(term)));
  }, [search, fixtures]);

  const handleSubmit = () => {
    if (!selected) return;
    onPatch({
      fixture: selected,
      fixtureNumber: startFix,
      count: Number(count),
      universe,
      startAddr,
      offset,
    });
    onClose();
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleSubmit();
    if (e.key === 'Escape') onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-bg text-white rounded-lg shadow-2xl w-full max-w-lg p-6"
        onClick={e => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="flex justify-between items-center mb-5">
          <h2 className="text-lg font-semibold">Patch Fixtures</h2>
          <button onClick={onClose} className="text-text-muted hover:text-white text-2xl leading-none w-8 h-8 flex items-center justify-center">×</button>
        </div>

        {/* Fixture search */}
        <div className="mb-2">
          <label className="block text-xs text-text-muted mb-1 uppercase tracking-wide">Fixture Type</label>
          <input
            ref={searchRef}
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search fixtures..."
            className="w-full px-3 py-2 bg-surface border border-border rounded text-white text-sm focus:outline-none focus:border-brand placeholder-gray-500"
          />
        </div>

        <div className="mb-4 h-36 overflow-auto bg-surface border border-border rounded">
          {filtered.length === 0 ? (
            <p className="p-3 text-text-muted text-sm">No fixtures found</p>
          ) : (
            filtered.map(f => (
              <button
                key={f.id}
                onClick={() => setSelected(f)}
                onMouseEnter={() => setHovered(f)}
                onMouseLeave={() => setHovered(null)}
                className={`w-full text-left px-3 py-2 text-sm border-b border-border last:border-0 flex justify-between items-center hover:bg-surface-2 ${
                  selected?.id === f.id ? 'bg-brand text-white' : 'text-text'
                }`}
              >
                <span className="font-medium">{f.fixture}</span>
                <span className="text-text-muted text-xs font-mono">{f.channelCount} ch · {f.wattage}W</span>
              </button>
            ))
          )}
        </div>

        <div className="mb-2 h-6 flex items-center">
          {hovered?.notes && (
            <p className="text-xs text-warn italic truncate">{hovered.notes}</p>
          )}
        </div>

        {selected && (
          <div className="mb-4 px-3 py-2 bg-surface border border-border rounded text-xs text-text-muted flex gap-4">
            <span className="text-white font-medium">{selected.fixture}</span>
            <span>{selected.channelCount} ch</span>
            <span>{selected.wattage}W</span>
            <span>{selected.weight} lbs</span>
            {selected.firmware && <span>FW {selected.firmware}</span>}
          </div>
        )}

        {/* Fixture number + count */}
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <label className="block text-xs text-text-muted mb-1 uppercase tracking-wide">Start Fix #</label>
            <input
              type="text"
              value={startFix}
              onChange={e => setStartFix(e.target.value)}
              placeholder="e.g. 101"
              className="w-full px-3 py-2 bg-surface border border-border rounded text-white text-sm focus:outline-none focus:border-brand placeholder-gray-500"
            />
          </div>
          <div>
            <label className="block text-xs text-text-muted mb-1 uppercase tracking-wide">Count</label>
            <input
              type="number"
              value={count}
              onChange={e => setCount(e.target.value)}
              min="1"
              className="w-full px-3 py-2 bg-surface border border-border rounded text-white text-sm focus:outline-none focus:border-brand"
            />
          </div>
        </div>

        {/* Universe / address / offset */}
        <div className="grid grid-cols-3 gap-3 mb-6">
          <div>
            <label className="block text-xs text-text-muted mb-1 uppercase tracking-wide">Universe</label>
            <input
              type="number"
              value={universe}
              onChange={e => setUniverse(e.target.value)}
              min="1"
              className="w-full px-3 py-2 bg-surface border border-border rounded text-white text-sm focus:outline-none focus:border-brand"
            />
          </div>
          <div>
            <label className="block text-xs text-text-muted mb-1 uppercase tracking-wide">Start Address</label>
            <input
              type="number"
              value={startAddr}
              onChange={e => setStartAddr(e.target.value)}
              min="1"
              max="512"
              className="w-full px-3 py-2 bg-surface border border-border rounded text-white text-sm focus:outline-none focus:border-brand"
            />
          </div>
          <div>
            <label className="block text-xs text-text-muted mb-1 uppercase tracking-wide">Offset</label>
            <input
              type="number"
              value={offset}
              onChange={e => setOffset(e.target.value)}
              min="0"
              className="w-full px-3 py-2 bg-surface border border-border rounded text-white text-sm focus:outline-none focus:border-brand"
            />
          </div>
        </div>

        <div className="flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm text-white">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!selected}
            className="px-4 py-2 bg-online hover:bg-online rounded text-sm font-medium text-white disabled:opacity-40"
          >
            Patch
          </button>
        </div>
      </div>
    </div>
  );
}
