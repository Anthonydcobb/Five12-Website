// Every timestamp this API serves is UTC. The backend now says so explicitly
// (a trailing `Z`), but a string with NO offset must still be read as UTC and
// never as local: `new Date("2026-07-21T20:57:05")` is parsed as LOCAL time per
// spec, which put every device 4h in the future, made elapsed time negative,
// and left `elapsed < 90_000` permanently true — so nothing was ever offline.
// This repo has a documented habit of leaving stale backends running, so the
// guard stays even though the serialization is fixed at the source.
export function parseUtc(iso) {
  if (!iso) return null;
  const hasZone = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasZone ? iso : `${iso}Z`);
}

export function timeAgo(iso) {
  if (!iso) return 'never';
  const secs = Math.floor((Date.now() - parseUtc(iso)) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}
