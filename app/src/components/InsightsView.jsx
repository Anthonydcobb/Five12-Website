import React from 'react';

export default function InsightsView({ fixtureTypeCounts, universeByLocation, universeBySet, fixtureReuse,
    patchName }) {
    const total = Object.values(fixtureTypeCounts).reduce((a, b) => a + b, 0);

    return (
        <div className="p-4 space-y-6">
            <section>
                <h2 className="text-xl mb-4 text-white">Fixture Type Breakdown</h2>
                {total === 0 ? (
                    <p className="text-gray-400">No fixtures found.</p>
                ) : (
                    <div className="space-y-2">
                        {Object.entries(fixtureTypeCounts)
                            .sort((a, b) => b[1] - a[1])
                            .map(([type, count]) => {
                                const percent = ((count / total) * 100).toFixed(1);
                                return (
                                    <div key={type}>
                                        <div className="text-sm text-white mb-1">
                                            {type} — {count} fixture{count !== 1 ? 's' : ''} ({percent}%)
                                        </div>
                                        <div className="h-4 bg-gray-700 rounded">
                                            <div
                                                className="h-4 bg-green-500 rounded"
                                                style={{ width: `${percent}%` }}
                                            />
                                        </div>
                                    </div>
                                );
                            })}
                    </div>
                )}
            </section>
            <section>
                <h2 className="text-xl mt-10 mb-4 text-white">Universe by Location</h2>
                {Object.keys(universeByLocation).length === 0 ? (
                    <p className="text-gray-400">No data available.</p>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="min-w-full text-sm text-left text-white border border-gray-700">
                            <thead className="bg-gray-800">
                                <tr>
                                    <th className="px-4 py-2 border">Location</th>
                                    <th className="px-4 py-2 border">Universes</th>
                                    <th className="px-4 py-2 border">Channels</th>
                                    <th className="px-4 py-2 border">Fixtures</th>
                                </tr>
                            </thead>
                            <tbody>
                                {Object.entries(universeByLocation).map(([loc, data]) => (
                                    <tr key={loc} className="border-t border-gray-700">
                                        <td className="px-4 py-1 border">{loc}</td>
                                        <td className="px-4 py-1 border">{data.universes.join(', ')}</td>
                                        <td className="px-4 py-1 border">{data.channelTotal}</td>
                                        <td className="px-4 py-1 border">{data.fixtures}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>
            <section>
                <h2 className="text-xl mt-10 mb-4 text-white">Universe by Set</h2>
                {Object.keys(universeBySet).length === 0 ? (
                    <p className="text-gray-400">No data available.</p>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="min-w-full text-sm text-left text-white border border-gray-700">
                            <thead className="bg-gray-800">
                                <tr>
                                    <th className="px-4 py-2 border">Set</th>
                                    <th className="px-4 py-2 border">Universes</th>
                                    <th className="px-4 py-2 border">Channels</th>
                                    <th className="px-4 py-2 border">Fixtures</th>
                                </tr>
                            </thead>
                            <tbody>
                                {Object.entries(universeBySet).map(([set, data]) => (
                                    <tr key={set} className="border-t border-gray-700">
                                        <td className="px-4 py-1 border">{set}</td>
                                        <td className="px-4 py-1 border">{data.universes.join(', ')}</td>
                                        <td className="px-4 py-1 border">{data.channelTotal}</td>
                                        <td className="px-4 py-1 border">{data.fixtures}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>
            <section>
                <h2 className="text-xl mt-10 mb-4 text-white">Fixture Reuse Across Sheets</h2>
                {fixtureReuse.length === 0 ? (
                    <p className="text-green-400">✅ No reused fixtures found across sheets.</p>
                ) : (
                    <ul className="text-sm text-white space-y-2">
                        {fixtureReuse.map((entry, i) => (
                            <li key={i} className="bg-yellow-900 px-4 py-2 rounded">
                                <strong>Fixture #{entry.fixture}</strong> is used in {entry.patchSheetIds.length} patch sheets.
                                {entry.isUsedHere && (
                                    <span className="ml-2 text-yellow-300">(also used in this sheet: {patchName})</span>
                                )}
                            </li>
                        ))}
                    </ul>
                )}
            </section>


        </div>
    );
}
