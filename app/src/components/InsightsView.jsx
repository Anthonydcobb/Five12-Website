import React, { useMemo } from 'react';

export default function InsightsView({ rows }) {
  const stats = useMemo(() => {
    const typeCounts = {};
    const universeChannels = {};
    const byLocation = {};
    const bySet = {};
    let totalWattage = 0;
    let totalWeight = 0;

    rows.forEach(r => {
      const type = r.type || 'Unknown';
      typeCounts[type] = (typeCounts[type] || 0) + 1;

      const ch = Number(r.channelCount) || 0;
      if (r.universe != null) {
        universeChannels[r.universe] = (universeChannels[r.universe] || 0) + ch;
      }

      const loc = r.location || 'Unassigned';
      if (!byLocation[loc]) byLocation[loc] = { fixtures: 0, channels: 0, universes: new Set() };
      byLocation[loc].fixtures += 1;
      byLocation[loc].channels += ch;
      if (r.universe != null) byLocation[loc].universes.add(r.universe);

      const set = r.set || 'Unassigned';
      if (!bySet[set]) bySet[set] = { fixtures: 0, channels: 0, universes: new Set() };
      bySet[set].fixtures += 1;
      bySet[set].channels += ch;
      if (r.universe != null) bySet[set].universes.add(r.universe);

      totalWattage += Number(r.wattage) || 0;
      totalWeight += Number(r.weight) || 0;
    });

    // Convert Sets to sorted arrays
    Object.values(byLocation).forEach(d => { d.universes = [...d.universes].sort((a, b) => a - b); });
    Object.values(bySet).forEach(d => { d.universes = [...d.universes].sort((a, b) => a - b); });

    return { typeCounts, universeChannels, byLocation, bySet, totalWattage, totalWeight };
  }, [rows]);

  const totalFixtures = rows.length;
  const totalChannels = Object.values(stats.universeChannels).reduce((a, b) => a + b, 0);

  const sortedTypes = Object.entries(stats.typeCounts).sort((a, b) => b[1] - a[1]);
  const sortedUniverses = Object.entries(stats.universeChannels).sort((a, b) => Number(a[0]) - Number(b[0]));

  return (
    <div className="space-y-8">

      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Fixtures', value: totalFixtures },
          { label: 'Universes', value: sortedUniverses.length },
          { label: 'Total Channels', value: totalChannels },
          { label: 'Total Wattage', value: `${stats.totalWattage.toLocaleString()} W` },
        ].map(s => (
          <div key={s.label} className="bg-gray-700 rounded-lg p-4">
            <div className="text-2xl font-bold text-white">{s.value}</div>
            <div className="text-xs text-gray-400 mt-1 uppercase tracking-wide">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

        {/* Fixture types */}
        <div className="bg-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-4">Fixture Types</h3>
          {sortedTypes.length === 0 ? (
            <p className="text-gray-500 text-sm">No data</p>
          ) : (
            <div className="space-y-3">
              {sortedTypes.map(([type, count]) => {
                const pct = ((count / totalFixtures) * 100).toFixed(0);
                return (
                  <div key={type}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-gray-300 truncate">{type}</span>
                      <span className="text-white font-mono ml-3">{count} <span className="text-gray-500 text-xs">({pct}%)</span></span>
                    </div>
                    <div className="w-full bg-gray-600 rounded-full h-1.5">
                      <div className="h-1.5 bg-green-400 rounded-full" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Universe usage */}
        <div className="bg-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-4">Universe Usage</h3>
          {sortedUniverses.length === 0 ? (
            <p className="text-gray-500 text-sm">No patched fixtures</p>
          ) : (
            <div className="space-y-3">
              {sortedUniverses.map(([univ, ch]) => {
                const pct = Math.min((ch / 512) * 100, 100).toFixed(0);
                const over = ch > 512;
                return (
                  <div key={univ}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-gray-300">Universe {univ}</span>
                      <span className={`font-mono ${over ? 'text-red-400' : 'text-white'}`}>
                        {ch} / 512 ch
                      </span>
                    </div>
                    <div className="w-full bg-gray-600 rounded-full h-1.5">
                      <div
                        className={`h-1.5 rounded-full ${over ? 'bg-red-500' : 'bg-blue-400'}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* By Location */}
      {Object.keys(stats.byLocation).length > 0 && (
        <div className="bg-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-4">By Location</h3>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-400 uppercase tracking-wide border-b border-gray-600">
                  <th className="pb-2 text-left font-semibold">Location</th>
                  <th className="pb-2 text-left font-semibold px-4">Universes</th>
                  <th className="pb-2 text-right font-semibold px-4">Channels</th>
                  <th className="pb-2 text-right font-semibold">Fixtures</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-600">
                {Object.entries(stats.byLocation).sort().map(([loc, d]) => (
                  <tr key={loc} className="text-gray-300">
                    <td className="py-2">{loc}</td>
                    <td className="py-2 px-4 font-mono text-xs">{d.universes.join(', ') || '—'}</td>
                    <td className="py-2 px-4 text-right font-mono">{d.channels}</td>
                    <td className="py-2 text-right font-mono">{d.fixtures}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* By Set */}
      {Object.keys(stats.bySet).length > 0 && (
        <div className="bg-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-4">By Set</h3>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-400 uppercase tracking-wide border-b border-gray-600">
                  <th className="pb-2 text-left font-semibold">Set</th>
                  <th className="pb-2 text-left font-semibold px-4">Universes</th>
                  <th className="pb-2 text-right font-semibold px-4">Channels</th>
                  <th className="pb-2 text-right font-semibold">Fixtures</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-600">
                {Object.entries(stats.bySet).sort().map(([set, d]) => (
                  <tr key={set} className="text-gray-300">
                    <td className="py-2">{set}</td>
                    <td className="py-2 px-4 font-mono text-xs">{d.universes.join(', ') || '—'}</td>
                    <td className="py-2 px-4 text-right font-mono">{d.channels}</td>
                    <td className="py-2 text-right font-mono">{d.fixtures}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

    </div>
  );
}
