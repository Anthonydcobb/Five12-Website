import React, { useState } from 'react';

export default function UniverseRow({ universe, fixtures, conflicts = [] }) {
    const channels = Array(512).fill(null);
    const fixtureColorMap = new Map();
    let colorIndex = 0;
    const blueShades = ['bg-blue-500', 'bg-blue-400', 'bg-blue-300', 'bg-blue-600'];

    fixtures.forEach(fix => {
        const start = fix.address - 1;
        const end = fix.endAddress - 1;
        const color = blueShades[colorIndex % blueShades.length];
        fixtureColorMap.set(fix.id, color);
        colorIndex++;

        for (let i = start; i <= end && i < 512; i++) {
            channels[i] = { ...fix, color };
        }
    });

    // Find gaps and total open channels
    let openGaps = [];
    let currentGap = null;
    let totalOpen = 0;

    for (let i = 0; i < 512; i++) {
        if (!channels[i]) {
            totalOpen++;
            if (!currentGap) {
                currentGap = { start: i + 1, end: i + 1 };
            } else {
                currentGap.end = i + 1;
            }
        } else if (currentGap) {
            openGaps.push({ ...currentGap });
            currentGap = null;
        }
    }
    if (currentGap) openGaps.push({ ...currentGap });

    const nextAvailable = openGaps.length > 0 ? openGaps[0].start : null;

    const [hoverInfo, setHoverInfo] = useState(null);

    return (
        <div className="mb-10 relative">
            <h3 className="mb-2 text-white text-lg">Universe {universe}</h3>

            {/* Tooltip UI */}
            {hoverInfo && (
                <div
                    className="absolute z-10 bg-gray-900 text-white text-sm p-3 rounded-md shadow-lg border border-gray-700 pointer-events-none"
                    style={{
                        left: hoverInfo.x + 12,
                        top: hoverInfo.y - 20,
                        minWidth: '160px'
                    }}
                >
                    {hoverInfo.fix ? (
                        <>
                            <div className="font-semibold text-blue-400 mb-1">Fix #{hoverInfo.fix.fixture}</div>
                            <div><strong>Type:</strong> {hoverInfo.fix.type}</div>
                            <div><strong>Ch Count:</strong> {hoverInfo.fix.channelCount}</div>
                            <div><strong>Ch:</strong> {hoverInfo.channel}</div>
                        </>
                    ) : (
                        <div><strong>Ch:</strong> {hoverInfo.channel}</div>
                    )}
                </div>
            )}

            <div
                className="grid grid-cols-64 gap-[1px] bg-gray-700 rounded overflow-hidden"
                onMouseLeave={() => setHoverInfo(null)}
            >
                {channels.map((fix, i) => (
                    <div
                        key={i}
                        className={`h-4 ${fix
                                ? conflicts.some(c =>
                                    (c.fixtureA.id === fix.id || c.fixtureB.id === fix.id)
                                )
                                    ? 'bg-red-600 hover:bg-red-500'
                                    : `${fix.color} hover:opacity-80`
                                : 'bg-gray-800 hover:bg-gray-600'
                            }`}
                        onMouseEnter={e => {
                            const rect = e.target.getBoundingClientRect();
                            const parentRect = e.currentTarget.parentNode.getBoundingClientRect();
                            setHoverInfo({
                                fix,
                                channel: i + 1,
                                x: rect.left - parentRect.left,
                                y: rect.top - parentRect.top
                            });
                        }}
                    />
                ))}
            </div>

            <div className="mt-2 text-sm text-gray-400 space-y-1">
                <div>
                    Next available channel: <span className="text-white font-medium">{nextAvailable || 'None'}</span>
                </div>
                <div>
                    Total open channels: <span className="text-white font-medium">{totalOpen}</span>
                </div>
                {openGaps.length > 0 && (
                    <div>
                        Gaps:
                        <ul className="list-disc ml-6 mt-1">
                            {openGaps.map((gap, i) => (
                                <li key={i} className="text-white">
                                    {gap.start} &gt; {gap.end} open: {gap.end - gap.start + 1}ch
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>
        </div>
    );
}
