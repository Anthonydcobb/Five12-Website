// File: src/components/Header.jsx — Five12 Logic design (1b Spotlight Stage)
import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import logo from '../assets/logo.svg';

const NAV = [
  { to: '/', label: 'Home' },
  { to: '/patch', label: 'Patch' },
  { to: '/labels', label: 'Labels' },
  { to: '/network', label: 'Network' },
  { to: '/devices', label: 'Devices' },
  { to: '/ip-config', label: 'IP Config' },
  { to: '/rf', label: 'RF Scanner' },
];

export default function Header() {
  const { pathname } = useLocation();
  const isActive = (to) => (to === '/' ? pathname === '/' : pathname.startsWith(to));

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-bg/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-screen-2xl items-center justify-between px-6 py-3">
        <Link to="/" className="shrink-0" style={{ filter: 'drop-shadow(0 0 18px oklch(60% 0.23 27 / 0.45))' }}>
          <img src={logo} alt="Five12 Logic" className="h-10" />
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
                    style={active ? { textShadow: '0 0 18px oklch(68% 0.22 27 / 0.55)' } : undefined}
                  >
                    {label}
                    {active && (
                      <span
                        className="absolute inset-x-2 -bottom-px h-px rounded-full bg-brand"
                        style={{ boxShadow: '0 0 10px oklch(60% 0.23 27 / 0.9)' }}
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
