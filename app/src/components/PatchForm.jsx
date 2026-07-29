import React, { useEffect, useRef, useState } from 'react';

const RESULT_LIMIT = 200;

export default function PatchForm({ onPatch, onClose }) {
  const [search, setSearch] = useState('');
  const [results, setResults] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [searchError, setSearchError] = useState('');
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
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setSearchError('');
      try {
        const params = new URLSearchParams({
          q: search.trim(), limit: String(RESULT_LIMIT),
        });
        const response = await fetch(`/api/fixture-library/patch-profiles?${params}`, {
          signal: controller.signal,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `Search failed (${response.status})`);
        setResults(data.items || []);
        setTotal(data.total || 0);
      } catch (error) {
        if (error.name !== 'AbortError') {
          setResults([]);
          setTotal(0);
          setSearchError(error.message);
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 200);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [search]);

  const handleSubmit = () => {
    if (!selected) return;
    onPatch({
      fixture: {
        ...selected,
        fixture: selected.displayName || selected.fixture,
      },
      fixtureNumber: startFix,
      count: Number(count),
      universe,
      startAddr,
      offset,
    });
    onClose();
  };

  const handleKeyDown = event => {
    if (event.key === 'Enter') handleSubmit();
    if (event.key === 'Escape') onClose();
  };

  const unknown = value => value == null || value === '' ? 'Unknown' : value;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="patch-fixtures-title"
        className="bg-bg text-white rounded-lg shadow-2xl w-full max-w-lg p-6"
        onClick={event => event.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="flex justify-between items-center mb-5">
          <h2 id="patch-fixtures-title" className="text-lg font-semibold">Patch Fixtures</h2>
          <button aria-label="Close" onClick={onClose} className="text-text-muted hover:text-white text-2xl leading-none w-8 h-8 flex items-center justify-center">×</button>
        </div>

        <div className="mb-2">
          <label className="block text-xs text-text-muted mb-1 uppercase tracking-wide">Fixture Type</label>
          <input
            ref={searchRef}
            type="search"
            value={search}
            onChange={event => { setSearch(event.target.value); setSelected(null); }}
            placeholder="Search manufacturer or profile…"
            className="w-full px-3 py-2 bg-surface border border-border rounded text-white text-sm focus:outline-none focus:border-brand placeholder-gray-500"
          />
        </div>

        <div className="mb-1 h-40 overflow-auto bg-surface border border-border rounded">
          {loading ? (
            <p className="p-3 text-text-muted text-sm">Searching fixture library…</p>
          ) : searchError ? (
            <p className="p-3 text-brand-hi text-sm">{searchError}</p>
          ) : results.length === 0 ? (
            <p className="p-3 text-text-muted text-sm">No patchable profiles found</p>
          ) : (
            results.map(profile => (
              <button
                key={profile.id}
                type="button"
                onClick={() => setSelected(profile)}
                onMouseEnter={() => setHovered(profile)}
                onMouseLeave={() => setHovered(null)}
                className={`w-full text-left px-3 py-2 text-sm border-b border-border last:border-0 flex justify-between items-center hover:bg-surface-2 ${
                  selected?.id === profile.id ? 'bg-brand text-white' : 'text-text'
                }`}
              >
                <span className="font-medium">{profile.displayName || profile.fixture}</span>
                <span className="text-text-muted text-xs font-mono">{profile.channelCount} ch</span>
              </button>
            ))
          )}
        </div>
        <p className="mb-3 text-xs text-text-muted">
          {total > RESULT_LIMIT
            ? `Showing the first ${RESULT_LIMIT} of ${total.toLocaleString()} matches — keep typing to narrow the list.`
            : `${total.toLocaleString()} patchable profile${total === 1 ? '' : 's'} found.`}
        </p>

        <div className="mb-2 h-6 flex items-center">
          {hovered?.notes && <p className="text-xs text-warn italic truncate">{hovered.notes}</p>}
        </div>

        {selected && (
          <div className="mb-4 px-3 py-2 bg-surface border border-border rounded text-xs text-text-muted flex flex-wrap gap-4">
            <span className="text-white font-medium">{selected.displayName || selected.fixture}</span>
            <span>{selected.channelCount} ch</span>
            <span>Wattage: {unknown(selected.wattage)}</span>
            <span>Weight: {unknown(selected.weight)}</span>
            {selected.firmware && <span>FW {selected.firmware}</span>}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <label className="block text-xs text-text-muted mb-1 uppercase tracking-wide">Start Fix #</label>
            <input type="text" value={startFix} onChange={event => setStartFix(event.target.value)} placeholder="e.g. 101" className="w-full px-3 py-2 bg-surface border border-border rounded text-white text-sm focus:outline-none focus:border-brand placeholder-gray-500" />
          </div>
          <div>
            <label className="block text-xs text-text-muted mb-1 uppercase tracking-wide">Count</label>
            <input type="number" value={count} onChange={event => setCount(event.target.value)} min="1" className="w-full px-3 py-2 bg-surface border border-border rounded text-white text-sm focus:outline-none focus:border-brand" />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 mb-6">
          <div>
            <label className="block text-xs text-text-muted mb-1 uppercase tracking-wide">Universe</label>
            <input type="number" value={universe} onChange={event => setUniverse(event.target.value)} min="1" className="w-full px-3 py-2 bg-surface border border-border rounded text-white text-sm focus:outline-none focus:border-brand" />
          </div>
          <div>
            <label className="block text-xs text-text-muted mb-1 uppercase tracking-wide">Start Address</label>
            <input type="number" value={startAddr} onChange={event => setStartAddr(event.target.value)} min="1" max="512" className="w-full px-3 py-2 bg-surface border border-border rounded text-white text-sm focus:outline-none focus:border-brand" />
          </div>
          <div>
            <label className="block text-xs text-text-muted mb-1 uppercase tracking-wide">Offset</label>
            <input type="number" value={offset} onChange={event => setOffset(event.target.value)} min="0" className="w-full px-3 py-2 bg-surface border border-border rounded text-white text-sm focus:outline-none focus:border-brand" />
          </div>
        </div>

        <div className="flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm text-white">Cancel</button>
          <button onClick={handleSubmit} disabled={!selected} className="px-4 py-2 bg-online hover:bg-online rounded text-sm font-medium text-white disabled:opacity-40">Patch</button>
        </div>
      </div>
    </div>
  );
}
