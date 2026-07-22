import React from 'react';
import logo from '../assets/logo.svg';

export default function Home() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[calc(100vh-4rem)] text-center px-4">
      <img
        src={logo}
        alt="Five12 Logo"
        className="w-56 mb-6"
        style={{ filter: 'drop-shadow(0 0 32px oklch(60% 0.23 27 / 0.45))' }}
      />
      <h1 className="text-5xl font-bold uppercase tracking-wide text-glow">Welcome</h1>
      <p className="mt-3 text-text-muted text-sm uppercase tracking-[0.25em]">
        Five12 Logic · Lighting Control
      </p>
    </div>
  );
}
