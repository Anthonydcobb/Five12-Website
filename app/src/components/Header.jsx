// File: src/components/Header.jsx — Five12 Logic design (1b Spotlight Stage)
// Unchanged except for the boot: the lockup is now <BootMark> (inline SVG, so
// it can sit dim while the rig comes up) and the nav lights with it. Outside a
// <BootProvider> the phase is the settled frame, so the header renders exactly
// as it did before.
import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { BootMark, BOOT_MARK_LIT, useBoot } from './BootLogo';

const NAV = [
  { to: '/', label: 'Home' },
  { to: '/patch', label: 'Patch' },
  { to: '/labels', label: 'Labels' },
  { to: '/network', label: 'Network' },
  { to: '/devices', label: 'Devices' },
  { to: '/ip-config', label: 'IP Config' },
];

export default function Header() {
  const { pathname } = useLocation();
  const isActive = (to) => (to === '/' ? pathname === '/' : pathname.startsWith(to));
  const { phase } = useBoot();
  const lit = phase.headerLit;
  const nav = phase.navLit;

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-bg/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-screen-2xl items-center justify-between px-6 py-3">
        <Link
          to="/"
          className="h-10 w-[59px] shrink-0"
          aria-label="Five12 Logic"
          style={{
            opacity: 0.18 + 0.82 * lit,
            filter: 'drop-shadow(0 0 18px oklch(60% 0.23 27 / ' + (0.45 * lit).toFixed(3) + '))',
          }}
        >
          <BootMark state={BOOT_MARK_LIT} uid="hdr" />
        </Link>
        <nav>
          <ul className="flex items-center gap-1">
            {NAV.map(({ to, label }) => {
              const active = isActive(to);
              return (
                <li key={to}>
                  <Link
                    to={to}
                    className={`relative rounded-lg px-3 py-2 font-display text-[15px] font-semibold uppercase tracking-wide transition-colors ${
                      active ? 'text-brand-hi' : 'text-text-muted hover:text-text'
                    }`}
                    style={{
                      opacity: active ? 0.22 + 0.78 * nav : 0.3 + 0.7 * nav,
                      textShadow: active
                        ? '0 0 18px oklch(68% 0.22 27 / ' + (0.55 * nav).toFixed(3) + ')'
                        : undefined,
                    }}
                  >
                    {label}
                    {active && (
                      <span
                        className="absolute inset-x-2 -bottom-px h-px rounded-full bg-brand"
                        style={{
                          opacity: nav,
                          boxShadow: '0 0 10px oklch(60% 0.23 27 / ' + (0.9 * nav).toFixed(3) + ')',
                        }}
                      />
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </header>
  );
}
