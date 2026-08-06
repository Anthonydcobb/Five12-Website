import { describe, expect, it } from 'vitest'
import { parseUtc, timeAgo } from './timeAgo'

// The no-offset guard in parseUtc exists because of a real, whole-feature bug
// and had zero direct coverage, before or after being promoted to a shared
// util. Every timestamp this API serves is UTC; a string with no offset is
// parsed as LOCAL time per the ECMAScript spec, which put every device
// `utcoffset` hours in the FUTURE, made elapsed time negative, and left
// `elapsed < 90_000` permanently true — so nothing was ever shown as offline
// and "remove offline devices" never found anything to remove.
describe('parseUtc', () => {
  it('reads an offset-less string as UTC, not as local time', () => {
    // Compared against an explicitly-UTC literal rather than a hardcoded
    // epoch, so the test means the same thing in every timezone the machine
    // running it might be set to.
    expect(parseUtc('2026-07-21T20:57:05').getTime())
      .toBe(Date.UTC(2026, 6, 21, 20, 57, 5))
  })

  it('is not the same as the local-time parse it exists to prevent', () => {
    // Skipped where the two coincide — on a UTC machine there is nothing to
    // distinguish, and asserting a difference there would fail spuriously.
    if (new Date().getTimezoneOffset() === 0) return
    expect(parseUtc('2026-07-21T20:57:05').getTime())
      .not.toBe(new Date('2026-07-21T20:57:05').getTime())
  })

  it('leaves a Z-suffixed string alone', () => {
    expect(parseUtc('2026-07-21T20:57:05Z').getTime())
      .toBe(Date.UTC(2026, 6, 21, 20, 57, 5))
  })

  it('respects an explicit +00:00 offset rather than appending a second zone', () => {
    // Appending `Z` to a string that already carries an offset produces
    // "...+00:00Z", which is an Invalid Date — the guard has to recognise
    // numeric offsets and not just the `Z` form.
    const parsed = parseUtc('2026-07-21T20:57:05+00:00')
    expect(Number.isNaN(parsed.getTime())).toBe(false)
    expect(parsed.getTime()).toBe(Date.UTC(2026, 6, 21, 20, 57, 5))
  })

  it('respects a non-zero offset', () => {
    expect(parseUtc('2026-07-21T20:57:05+04:00').getTime())
      .toBe(Date.UTC(2026, 6, 21, 16, 57, 5))
  })

  it('returns null for a missing timestamp', () => {
    expect(parseUtc(null)).toBe(null)
    expect(parseUtc('')).toBe(null)
  })
})

describe('timeAgo', () => {
  it('returns "never" for a missing timestamp', () => {
    expect(timeAgo(null)).toBe('never')
    expect(timeAgo(undefined)).toBe('never')
  })

  it('reports an offset-less UTC timestamp as elapsed, never as the future', () => {
    // The bug in one assertion: an offset-less string 4 minutes old must read
    // as 4 minutes ago, not as a negative interval that reads as "0s ago".
    const iso = new Date(Date.now() - 240_000).toISOString().replace('Z', '')
    expect(timeAgo(iso)).toBe('4m ago')
  })

  it('counts seconds, then minutes, then hours', () => {
    expect(timeAgo(new Date(Date.now() - 5_000).toISOString())).toBe('5s ago')
    expect(timeAgo(new Date(Date.now() - 300_000).toISOString())).toBe('5m ago')
    expect(timeAgo(new Date(Date.now() - 7_200_000).toISOString())).toBe('2h ago')
  })
})
