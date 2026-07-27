// Shows WHERE a value came from. The distinction matters: an advertisement is
// passive and proves only presence, while a GATT read required a connection.
const LABELS = {
  'service-uuid': 'service UUID',
  'manufacturer-data': 'mfr data',
  'gatt-read': 'GATT read',
  mirror: 'mirror',
  sim: 'simulated',
}

export default function BleEvidenceBadge({ source }) {
  if (!source) return null
  return (
    <span className="text-[8px] font-mono px-1 py-[1px] rounded-sm border border-[var(--color-border)] text-text-muted">
      {LABELS[source] || source}
    </span>
  )
}
