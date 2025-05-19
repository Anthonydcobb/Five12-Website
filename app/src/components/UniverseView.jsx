import React from 'react';
import UniverseRow from './UniverseRow';

export default function UniverseView({ rows, conflicts = [] }) {
  const grouped = {};

  rows.forEach(row => {
    if (!grouped[row.universe]) grouped[row.universe] = [];
    grouped[row.universe].push(row);
  });

  const sortedUniverses = Object.keys(grouped).sort((a, b) => a - b);

  return (
    <div className="p-6 bg-gray-900 min-h-screen">
      {sortedUniverses.map(univ => (
        <UniverseRow
          key={univ}
          universe={univ}
          fixtures={grouped[univ]}
          conflicts={conflicts.filter(c => String(c.universe) === String(univ))}
        />
      ))}
    </div>
  );
}
