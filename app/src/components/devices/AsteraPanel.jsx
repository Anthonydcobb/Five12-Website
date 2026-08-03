import { useEffect, useState } from 'react'
import axios from 'axios'

// Astera ART7 — read-only telemetry via the AsteraNext RemoteControl API.
//
// Language rules, mirroring the backend contract:
//   "disabled" is not "not found"  — while FIVE12_ASTERA_TOOLS is off we never
//                                    looked, and the copy must not imply we did
//   simulated data says so loudly  — and only real reads carry the
//                                    "protocol unverified" caveat (the payload
//                                    shapes come from static analysis, not a
//                                    captured AsteraNext server)
//   PIN alias only                 — the raw Radio PIN never reaches the UI

const POLL_MS = 3000

function useAsteraStatus() {
  const [status, setStatus] = useState(null)
  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const { data } = await axios.get('/api/devices/astera/status')
        if (alive) setStatus(data)
      } catch {
        if (alive) setStatus({ available: false, reason: 'backend unreachable' })
      }
    }
    poll()
    const i = setInterval(poll, POLL_MS)
    return () => { alive = false; clearInterval(i) }
  }, [])
  return status
}

function Badge({ tone, children }) {
  return (
    <span className={`text-[8px] font-mono uppercase tracking-widest px-1.5 py-0.5 border ${tone}`}>
      {children}
    </span>
  )
}

export default function AsteraPanel() {
  const status = useAsteraStatus()

  if (!status) {
    return <div className="text-[10px] font-mono text-text-muted py-6 px-2">loading…</div>
  }

  if (!status.available) {
    return (
      <div className="p-3 space-y-2">
        <div className="text-[10px] font-mono text-text-muted py-4 px-2">
          device unavailable{status.reason ? <> — <span>{status.reason}</span></> : ''}
        </div>
        <Footer />
      </div>
    )
  }

  const bridge = status.bridge || {}

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-[11px] font-mono font-bold text-gel">{bridge.name ?? '—'}</span>
        <span className="text-[10px] font-mono text-text-muted">
          bridge battery {bridge.batteryPct != null ? `${bridge.batteryPct}%` : '—'}
        </span>
        <span className="text-[10px] font-mono text-text-muted">
          app {status.appOnline ? 'online' : 'offline'}
          {status.appVersion ? ` · ${status.appVersion}` : ''}
        </span>
        {status.radioPinAlias && (
          <span className="text-[9px] font-mono text-text-muted border border-[var(--color-surface-2)] px-1.5 py-0.5">
            {status.radioPinAlias}
          </span>
        )}
        {status.simulated ? (
          <Badge tone="text-warn border-warn">simulated</Badge>
        ) : status.protocolVerified === false ? (
          <Badge tone="text-text-muted border-[var(--color-surface-2)]">protocol unverified</Badge>
        ) : null}
      </div>

      {(status.alerts || []).map((a, i) => (
        <div key={i}
             className={`text-[9px] font-mono ${a.level === 'crit' ? 'text-brand-hi' : 'text-warn'}`}>
          {a.message}
        </div>
      ))}

      <div>
        <div className="text-[9px] font-mono uppercase tracking-widest text-text-muted mb-1">
          targets ({status.targetCount ?? 0})
        </div>
        <table className="w-full text-[10px] font-mono">
          <tbody>
            {(status.targets || []).map((t) => (
              <tr key={t.id ?? t.name} className="border-t border-[var(--color-surface-2)]">
                <td className="py-1 pr-2">{t.name ?? '—'}</td>
                <td className="py-1 pr-2 text-text-muted">
                  {t.brightnessPct != null ? `${t.brightnessPct}%` : '—'}
                </td>
                <td className="py-1 text-text-muted">{t.selected ? 'selected' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Footer />
    </div>
  )
}

function Footer() {
  return (
    <div className="text-[8px] text-text-muted font-mono border-t border-[var(--color-surface-2)] pt-2">
      read-only · /api/status + /api/targets via AsteraNext RemoteControl · gate: FIVE12_ASTERA_TOOLS
    </div>
  )
}
