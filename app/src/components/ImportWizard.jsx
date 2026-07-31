import React, { useRef, useState } from 'react';

const FIELDS = [
  ['set', 'Set'], ['fixture', 'Fix #'], ['universe', 'Universe'],
  ['address', 'Address'], ['endAddress', 'End Addr'], ['type', 'Fixture Type'],
  ['channelCount', 'CH Count'], ['location', 'Location'], ['wattage', 'Wattage'],
  ['weight', 'Weight'], ['firmware', 'Firmware'], ['notes', 'Notes'],
];
const LABEL = Object.fromEntries(FIELDS);

// Parse a fetch Response defensively: the body may not be JSON at all (a
// 413 payload-too-large, a proxy error page, or a Flask 500 HTML page).
async function readJson(res) {
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON body */ }
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
  return data || {};
}

function profileLabel(profile) {
  return profile?.displayName || [profile?.manufacturer, profile?.fixture].filter(Boolean).join(' — ');
}

function isCompatible(group, profile) {
  return group.channelCount == null || Number(profile.channelCount) === Number(group.channelCount);
}

export default function ImportWizard({ patchId, onClose, onImported }) {
  const [file, setFile] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [mapping, setMapping] = useState({});
  const [step, setStep] = useState('mapping');
  const [groups, setGroups] = useState([]);
  const [selections, setSelections] = useState({});
  const [selectedProfiles, setSelectedProfiles] = useState({});
  const [unmatchedAcknowledged, setUnmatchedAcknowledged] = useState({});
  const [searches, setSearches] = useState({});
  const [customForms, setCustomForms] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const searchGeneration = useRef({});

  const uploadForm = (includeSelections = false) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('mapping', JSON.stringify(mapping));
    fd.append('headerRowIndex', String(analysis.headerRowIndex));
    if (includeSelections) fd.append('fixtureSelections', JSON.stringify(selections));
    return fd;
  };

  const analyze = async (pickedFile) => {
    setBusy(true); setError(null);
    try {
      const fd = new FormData();
      fd.append('file', pickedFile);
      const res = await fetch(`/api/patch-sheets/${patchId}/import/analyze`,
        { method: 'POST', body: fd });
      const data = await readJson(res);
      setAnalysis(data);
      setMapping(data.suggestedMapping || {});
      setStep('mapping');
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const onPick = (e) => {
    const pickedFile = e.target.files[0];
    if (!pickedFile) return;
    setFile(pickedFile);
    analyze(pickedFile);
  };

  const reviewMatches = async () => {
    setBusy(true); setError(null);
    try {
      const res = await fetch(`/api/patch-sheets/${patchId}/import/matches`,
        { method: 'POST', body: uploadForm() });
      const data = await readJson(res);
      const nextGroups = data.groups || [];
      const nextSelections = {};
      const nextProfiles = {};
      const nextSearches = {};
      nextGroups.forEach((group) => {
        nextSelections[group.key] = group.selectedFixtureId ?? null;
        const selected = group.suggestions?.find(item => item.id === group.selectedFixtureId);
        if (selected) nextProfiles[group.key] = selected;
        nextSearches[group.key] = { query: group.sourceType, results: [], busy: false, error: null };
      });
      setGroups(nextGroups);
      setSelections(nextSelections);
      setSelectedProfiles(nextProfiles);
      setUnmatchedAcknowledged({});
      setSearches(nextSearches);
      setCustomForms({});
      setStep('matching');
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const chooseProfile = (group, profile) => {
    if (!isCompatible(group, profile)) return;
    setSelections(current => ({ ...current, [group.key]: profile.id }));
    setSelectedProfiles(current => ({ ...current, [group.key]: profile }));
    setUnmatchedAcknowledged(current => ({ ...current, [group.key]: false }));
  };

  const keepUnmatched = (group) => {
    setSelections(current => ({ ...current, [group.key]: null }));
    setSelectedProfiles(current => {
      const next = { ...current };
      delete next[group.key];
      return next;
    });
    setUnmatchedAcknowledged(current => ({ ...current, [group.key]: true }));
  };

  const updateSearch = (key, query) => {
    setSearches(current => ({
      ...current,
      [key]: { ...(current[key] || {}), query, error: null },
    }));
  };

  const searchLibrary = async (group) => {
    const state = searches[group.key] || {};
    const query = (state.query || group.sourceType || '').trim();
    const generation = (searchGeneration.current[group.key] || 0) + 1;
    searchGeneration.current[group.key] = generation;
    setSearches(current => ({
      ...current,
      [group.key]: { ...(current[group.key] || {}), query, busy: true, error: null },
    }));
    try {
      const params = new URLSearchParams({ q: query, limit: '25', offset: '0' });
      const res = await fetch(`/api/fixture-library/patch-profiles?${params}`);
      const data = await readJson(res);
      if (searchGeneration.current[group.key] !== generation) return;
      setSearches(current => ({
        ...current,
        [group.key]: { ...(current[group.key] || {}), results: data.items || [], busy: false, error: null },
      }));
    } catch (e) {
      if (searchGeneration.current[group.key] !== generation) return;
      setSearches(current => ({
        ...current,
        [group.key]: { ...(current[group.key] || {}), busy: false, error: e.message },
      }));
    }
  };

  const toggleCustom = (group) => {
    setCustomForms(current => ({
      ...current,
      [group.key]: current[group.key] ? null : {
        manufacturer: '', fixture: group.sourceType, channelCount: group.channelCount ?? '', busy: false, error: null,
      },
    }));
  };

  const updateCustom = (key, field, value) => {
    setCustomForms(current => ({
      ...current,
      [key]: { ...current[key], [field]: value, error: null },
    }));
  };

  const createCustom = async (group) => {
    const form = customForms[group.key];
    setCustomForms(current => ({
      ...current, [group.key]: { ...current[group.key], busy: true, error: null },
    }));
    try {
      const res = await fetch('/api/fixtures', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          manufacturer: form.manufacturer,
          fixture: form.fixture,
          channelCount: Number(form.channelCount),
          notes: 'Created during patch-sheet import',
        }),
      });
      const profile = await readJson(res);
      chooseProfile(group, profile);
      setCustomForms(current => ({ ...current, [group.key]: null }));
    } catch (e) {
      setCustomForms(current => ({
        ...current, [group.key]: { ...current[group.key], busy: false, error: e.message },
      }));
    }
  };

  const commit = async () => {
    setBusy(true); setError(null);
    try {
      const res = await fetch(`/api/patch-sheets/${patchId}/import/commit`,
        { method: 'POST', body: uploadForm(true) });
      const data = await readJson(res);
      onImported(data);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const targets = Object.values(mapping).filter(Boolean);
  const dupes = targets.filter((target, index) => targets.indexOf(target) !== index);
  const allGroupsReviewed = groups.every(group =>
    selections[group.key] != null || unmatchedAcknowledged[group.key]);

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-surface border border-border rounded-lg p-6 w-[min(94vw,980px)] max-h-[88vh] overflow-auto shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold">Import Patch Sheet</h3>
            {analysis && <p className="text-xs text-text-muted mt-1">Map columns → Match fixtures → Import</p>}
          </div>
          <button aria-label="Close import" onClick={onClose} className="text-text-muted hover:text-text text-lg leading-none">×</button>
        </div>

        {error && (
          <div role="alert" className="bg-brand-dim/30 border border-brand/40 text-brand-hi text-sm rounded px-3 py-2 mb-3">{error}</div>
        )}

        {!analysis ? (
          <label className="block border border-dashed border-border rounded-lg p-8 text-center cursor-pointer hover:border-muted">
            <div className="text-text-muted text-sm">Choose an .xlsx or .csv patch sheet</div>
            <input type="file" accept=".xlsx,.csv" className="hidden" onChange={onPick} />
          </label>
        ) : step === 'mapping' ? (
          <>
            <p className="text-text-muted text-sm mb-3">
              {analysis.rowCount} rows · header row {analysis.headerRowIndex + 1}. Map their columns to yours:
            </p>
            {dupes.length > 0 && (
              <div className="bg-warn/15 border border-warn/40 text-warn text-xs rounded px-3 py-2 mb-3">
                Two columns map to the same field ({[...new Set(dupes)].map(item => LABEL[item]).join(', ')}); the last one wins.
              </div>
            )}
            <table className="w-full text-sm mb-4">
              <thead><tr className="text-text-muted text-xs uppercase tracking-wide">
                <th className="text-left py-1">Their column</th><th className="text-left py-1">→ Your column</th><th className="text-left py-1">Sample</th>
              </tr></thead>
              <tbody>
                {analysis.theirColumns.map(column => (
                  <tr key={column} className="border-t border-border">
                    <td className="py-1.5 pr-3 font-mono">{column}</td>
                    <td className="py-1.5 pr-3">
                      <select aria-label={`Map ${column}`} value={mapping[column] || 'ignore'}
                        onChange={event => setMapping(current => ({ ...current, [column]: event.target.value === 'ignore' ? null : event.target.value }))}
                        className="bg-bg border border-border rounded px-2 py-1 text-text">
                        <option value="ignore">— Ignore —</option>
                        {FIELDS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                      </select>
                    </td>
                    <td className="py-1.5 text-text-muted font-mono truncate max-w-[180px]">{String(analysis.previewRows[0]?.[column] ?? '')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex justify-end gap-3">
              <button onClick={onClose} className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm">Cancel</button>
              <button onClick={reviewMatches} disabled={busy || dupes.length > 0}
                className="px-4 py-2 bg-online hover:brightness-110 text-bg rounded text-sm font-medium disabled:opacity-40">
                {busy ? 'Checking library…' : 'Review fixture matches'}
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="text-sm text-text-muted mb-4">
              Exact matches are selected automatically. Suggested or unmatched profiles need your choice. A selected profile must have the same DMX footprint as the imported row.
            </p>
            {groups.length === 0 && (
              <div className="border border-warn/40 bg-warn/10 rounded p-3 text-sm mb-4">
                No fixture-type column was found. Rows will import without fixture-library matching.
              </div>
            )}
            <div className="space-y-4 mb-5">
              {groups.map(group => {
                const selected = selectedProfiles[group.key];
                const exact = selected && group.suggestions?.some(item => item.id === selected.id && item.exact);
                const search = searches[group.key] || {};
                const custom = customForms[group.key];
                return (
                  <section key={group.key} className="border border-border rounded-lg p-4 bg-bg/40">
                    <div className="flex flex-wrap justify-between gap-2 mb-2">
                      <div>
                        <div className="font-medium">{group.sourceType}</div>
                        <div className="text-xs text-text-muted">{group.channelCount ?? 'Unknown'} channels · {group.rowCount} row{group.rowCount === 1 ? '' : 's'}</div>
                      </div>
                      <div className={`text-xs font-medium ${selected ? 'text-online' : unmatchedAcknowledged[group.key] ? 'text-warn' : 'text-brand-hi'}`}>
                        {selected ? (exact ? 'Exact match' : 'Profile selected') : unmatchedAcknowledged[group.key] ? 'Will import unmatched' : 'Not matched'}
                      </div>
                    </div>

                    {selected && <div className="text-sm text-online mb-2">Selected: {profileLabel(selected)} · {selected.channelCount}ch</div>}

                    {!selected && group.suggestions?.length > 0 && (
                      <div className="mb-3">
                        <div className="text-xs uppercase tracking-wide text-text-muted mb-1">Closest compatible profiles</div>
                        <div className="flex flex-wrap gap-2">
                          {group.suggestions.map(profile => (
                            <button key={profile.id} onClick={() => chooseProfile(group, profile)}
                              aria-label={`Choose ${profileLabel(profile)}`}
                              className="text-xs border border-border hover:border-online rounded px-2 py-1">
                              {profileLabel(profile)} · {profile.channelCount}ch · {Math.round((profile.score || 0) * 100)}%
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="flex gap-2 mb-2">
                      <input aria-label={`Search profile for ${group.sourceType}`} value={search.query || ''}
                        onChange={event => updateSearch(group.key, event.target.value)}
                        onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); searchLibrary(group); } }}
                        className="flex-1 min-w-0 bg-surface border border-border rounded px-2 py-1 text-sm"
                        placeholder="Search manufacturer, fixture, or mode" />
                      <button aria-label={`Search library for ${group.sourceType}`} onClick={() => searchLibrary(group)} disabled={search.busy}
                        className="px-3 py-1 bg-surface-2 hover:bg-border rounded text-sm disabled:opacity-40">
                        {search.busy ? 'Searching…' : 'Search'}
                      </button>
                    </div>
                    {search.error && <div className="text-xs text-brand-hi mb-2">{search.error}</div>}
                    {search.results?.length > 0 && (
                      <div className="max-h-36 overflow-auto border border-border rounded mb-3 divide-y divide-border">
                        {search.results.map(profile => {
                          const compatible = isCompatible(group, profile);
                          const label = profileLabel(profile);
                          return (
                            <button key={profile.id} disabled={!compatible} onClick={() => chooseProfile(group, profile)}
                              aria-label={compatible ? `Choose ${label}` : `${label} — footprint mismatch`}
                              className="w-full text-left px-2 py-1.5 text-xs hover:bg-surface-2 disabled:opacity-40 disabled:cursor-not-allowed">
                              {label} · {profile.channelCount}ch{compatible ? '' : ` — footprint mismatch (${group.channelCount}ch imported)`}
                            </button>
                          );
                        })}
                      </div>
                    )}

                    <div className="flex flex-wrap gap-2">
                      <button onClick={() => toggleCustom(group)} aria-label={`Add ${group.sourceType} to fixture database`}
                        className="text-xs px-2 py-1 border border-border hover:border-online rounded">
                        Add to fixture database
                      </button>
                      <button onClick={() => keepUnmatched(group)} aria-label={`Keep ${group.sourceType} unmatched`}
                        className="text-xs px-2 py-1 border border-warn/50 text-warn rounded">
                        Import unmatched
                      </button>
                    </div>

                    {custom && (
                      <div className="mt-3 grid grid-cols-1 sm:grid-cols-[1fr_2fr_90px_auto] gap-2 p-3 bg-surface rounded border border-border">
                        <input aria-label="Custom manufacturer" placeholder="Manufacturer" value={custom.manufacturer}
                          onChange={event => updateCustom(group.key, 'manufacturer', event.target.value)}
                          className="bg-bg border border-border rounded px-2 py-1 text-sm" />
                        <input aria-label="Custom fixture profile name" value={custom.fixture}
                          onChange={event => updateCustom(group.key, 'fixture', event.target.value)}
                          className="bg-bg border border-border rounded px-2 py-1 text-sm" />
                        <input aria-label="Custom fixture channel count" type="number" min="1" max="512" value={custom.channelCount}
                          onChange={event => updateCustom(group.key, 'channelCount', event.target.value)}
                          className="bg-bg border border-border rounded px-2 py-1 text-sm" />
                        <button onClick={() => createCustom(group)} disabled={custom.busy}
                          className="px-3 py-1 bg-online text-bg rounded text-sm disabled:opacity-40">
                          {custom.busy ? 'Creating…' : 'Create and select fixture'}
                        </button>
                        {custom.error && <div className="sm:col-span-4 text-xs text-brand-hi">{custom.error}</div>}
                      </div>
                    )}
                  </section>
                );
              })}
            </div>
            <div className="flex justify-between gap-3">
              <button onClick={() => setStep('mapping')} disabled={busy} className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm">Back to mapping</button>
              <div className="flex gap-3">
                <button onClick={onClose} className="px-4 py-2 bg-surface-2 hover:bg-border rounded text-sm">Cancel</button>
                <button onClick={commit} disabled={busy || !allGroupsReviewed}
                  className="px-4 py-2 bg-online hover:brightness-110 text-bg rounded text-sm font-medium disabled:opacity-40">
                  {busy ? 'Importing…' : `Import ${analysis.rowCount} rows`}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
