import { useEffect, useRef, useState } from 'react'
import { fetchBleDevices, fetchBleSnapshot, signalBars } from '../../lib/bleApi'
import BleEvidenceBadge from './BleEvidenceBadge'

// Language rules from the verified protocol reference, enforced in copy:
//   "nearby" is not "connected"      — the roster carries no GATT fields
//   "TimoTwo-compatible" is not      — the radio platform does not identify
//     "Cintenna 2"                     the enclosure
//   RSSI is not distance             — bars and raw dBm only, never metres

function Bars({ rssi }) {
  const bars = signalBars(rssi)
  return (
    <span className="inline-flex items-end gap-[2px] h-3" title={`${rssi} dBm`}>
      {[1, 2, 3, 4].map((n) => (
        <span
          key={n}
          className={'w-[3px] ' + (n <= bars ? 'bg-brand' : 'bg-[var(--color-surface-2)]')}
          style={{ height: `${n * 25}%` }}
        />
      ))}
    </span>
  )
}

function Field({ label, value, source, suffix = '' }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-[2px]">
      <span className="text-[9px] font-mono text-text-muted uppercase">{label}</span>
      <span className="flex items-center gap-2">
        <span className="text-[11px] font-mono text-text">
          {value === null || value === undefined ? '—' : `${value}${suffix}`}
        </span>
        <BleEvidenceBadge source={source} />
      </span>
    </div>
  )
}

export default function CintennaPanel() {
  const [roster, setRoster] = useState(null)
  const [selected, setSelected] = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [snapError, setSnapError] = useState(null)
  const [reading, setReading] = useState(false)

  // The roster buttons stay clickable while a read is in flight, so the
  // operator can switch radios mid-read. readStatus's closure freezes
  // `selected` at click time, so we need a ref that always reflects the
  // *current* selection to check against when the response comes back.
  const selectedRef = useRef(selected)
  selectedRef.current = selected

  useEffect(() => {
    let alive = true
    const poll = async () => {
      const data = await fetchBleDevices()
      if (alive) setRoster(data)
    }
    poll()
    const i = setInterval(poll, 5000)
    return () => { alive = false; clearInterval(i) }
  }, [])

  const readStatus = async () => {
    const requestedOsId = selected.osId
    setReading(true)
    setSnapError(null)
    setSnapshot(null)
    try {
      const data = await fetchBleSnapshot(requestedOsId)
      // Only apply the response if the operator is still looking at the
      // device it was requested for. If they switched roster selection
      // while this was in flight, applying it would attribute another
      // radio's battery/firmware/mode to the currently-selected one.
      if (selectedRef.current?.osId === requestedOsId) {
        setSnapshot(data)
      }
    } catch (err) {
      if (selectedRef.current?.osId === requestedOsId) {
        setSnapError(err)
      }
    } finally {
      // Always clear, even for a discarded response, so the Read status
      // button never gets stuck showing "reading…" for whichever device
      // is selected now.
      setReading(false)
    }
  }

  if (!roster) {
    return <div className="text-[10px] font-mono text-text-muted py-2">scanning…</div>
  }

  if (roster.unavailable) {
    return (
      <div className="text-[10px] font-mono text-text-muted py-2 leading-relaxed">
        Bluetooth tools are switched off.<br />
        Set <span className="text-text">FIVE12_BLE_TOOLS=1</span> and restart the
        backend to discover CRMX devices.
      </div>
    )
  }

  if (roster.error) {
    return (
      <div className="text-[10px] font-mono text-text-muted py-2 leading-relaxed">
        Could not reach the Bluetooth scan service.<br />
        Reload this page; if it keeps happening, check the backend log.
      </div>
    )
  }

  const fields = snapshot?.fields || {}
  // Roster is replaced wholesale on every 5s poll; reconcile the selection
  // against it so a radio that walked out of range doesn't keep rendering
  // as if it were still there.
  const selectedNearby = !selected || roster.devices.some((d) => d.osId === selected.osId)

  return (
    <div className="space-y-3">
      <div className="text-[9px] font-mono text-text-muted">
        passive Bluetooth scan · nearby is not connected · signal strength is not distance
      </div>

      {roster.devices.length === 0 && (
        <div className="text-[10px] font-mono text-text-muted py-2">
          no CRMX devices nearby
        </div>
      )}

      <div className="flex gap-2 flex-wrap">
        {roster.devices.map((d) => (
          <button
            key={d.osId}
            onClick={() => { setSelected(d); setSnapshot(null); setSnapError(null) }}
            aria-pressed={selected?.osId === d.osId}
            className={'text-left px-3 py-2 rounded-sm border min-w-[200px] ' +
              (selected?.osId === d.osId
                ? 'border-brand bg-brand-dim/30'
                : 'border-[var(--color-border)] bg-[var(--color-surface)] hover:border-border')}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-mono font-bold text-text">
                {d.localName || '(unnamed)'}
              </span>
              <Bars rssi={d.rssiSmoothed} />
            </div>
            <div className="text-[8px] font-mono text-text-muted mt-[2px]">
              TimoTwo-compatible · {d.rssi} dBm
            </div>
            <div className="flex gap-1 mt-1">
              {(d.evidence || []).map((e) => <BleEvidenceBadge key={e} source={e} />)}
            </div>
          </button>
        ))}
      </div>

      {selected && (
        <div className="border border-[var(--color-border)] rounded-sm p-3 max-w-md">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-mono font-bold text-text">
              {selected.localName}
            </span>
            <button
              onClick={readStatus}
              disabled={reading || !selectedNearby}
              className="text-[9px] font-mono px-2 py-1 border border-[var(--color-border)] rounded-sm hover:border-brand disabled:opacity-40"
            >
              {reading ? 'reading…' : 'Read status'}
            </button>
          </div>

          <Field label="hardware id" value={selected.hardwareId} source="manufacturer-data" />

          {!selectedNearby && (
            <div className="text-[10px] font-mono text-text-muted mt-2 leading-relaxed">
              {selected.localName || '(unnamed)'} is no longer nearby.
            </div>
          )}

          {snapError && (
            <div className="text-[10px] font-mono text-amber-400 mt-2 leading-relaxed">
              {snapError.message}
            </div>
          )}

          {snapshot && (
            <div className="mt-2 border-t border-[var(--color-surface-2)] pt-2">
              <Field label="battery" value={fields.battery?.decoded} suffix="%"
                     source={fields.battery?.source} />
              <Field label="firmware" value={fields.firmware?.decoded}
                     source={fields.firmware?.source} />
              <Field label="mode" value={fields.mode?.decoded?.toUpperCase()}
                     source={fields.mode?.source} />
              <Field label="dmx hold"
                     value={fields.dmxHold?.decoded === undefined ? null
                            : fields.dmxHold.decoded ? 'On' : 'Off'}
                     source={fields.dmxHold?.source} />
              {fields.outputPower && (
                <Field label="output power"
                       value={fields.outputPower.notApplicable
                              ? 'n/a in RX'
                              : fields.outputPower.toolboxLabel || fields.outputPower.decoded}
                       source={fields.outputPower.source} />
              )}
              {fields.txProtocol && (
                <Field label="protocol"
                       value={fields.txProtocol.notApplicable
                              ? 'n/a in RX'
                              : fields.txProtocol.decoded?.toUpperCase()}
                       source={fields.txProtocol.source} />
              )}
              {snapshot.warnings?.length > 0 && (
                <div className="text-[8px] font-mono text-text-muted mt-2">
                  {snapshot.warnings.join(' · ')}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="text-[8px] text-text-muted font-mono border-t border-[var(--color-surface-2)] pt-2">
        read-only · passive BLE advertisement + connected GATT reads · no configuration writes
      </div>
    </div>
  )
}
