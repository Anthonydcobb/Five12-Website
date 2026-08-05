// src/pages/Home.jsx — home screen with the boot sequence.
// Layout, type and spacing are unchanged from the previous Home.jsx; the logo
// is now <BootMark> (inline SVG, so its parts can be lit separately) and the
// copy reveals as the rig comes up. Falls back to the settled frame instantly
// under prefers-reduced-motion.
import React from 'react';
import { BootMark, useBoot } from '../components/BootLogo';

// Copy: sentence case in source, uppercased by the type styles.
const HEADLINE = 'Ready';
const SUBLINE = 'Five12 Logic · Lighting Control';
const STATUSLINE = 'Backend online · 2 interfaces · no show loaded';

export default function Home() {
  // one clock for the whole shell — the header lights up with the rig
  const { phase: s, start } = useBoot();
  React.useEffect(() => { start(); }, [start]);

  return (
    <div className="relative flex min-h-[calc(100vh-4rem)] flex-col items-center justify-center px-4 text-center">
      {/* the stage wash brightens while the rig strikes, then settles back */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(130% 90% at 50% -15%, oklch(30% 0.12 27 / ' +
            (0.3 * s.wash).toFixed(3) + '), transparent 62%)',
        }}
      />

      {/* patch readout — only while the universe is being read */}
      <div
        className="absolute top-24 font-mono text-[11px] uppercase tracking-[0.18em] text-text-muted"
        style={{ opacity: s.readout }}
      >
        {s.readoutText}
      </div>

      <div
        className="mb-6 w-56"
        style={{
          transform: 'translateY(' + s.lift.toFixed(2) + 'px) scale(' + s.scale.toFixed(4) + ')',
          transformOrigin: '50% 50%',
          filter:
            'drop-shadow(0 0 ' + (32 + 78 * s.glow).toFixed(1) +
            'px oklch(60% 0.23 27 / ' + (0.45 + 0.4 * s.glow).toFixed(3) + '))',
        }}
      >
        <BootMark state={s.logo} uid="home" />
      </div>

      <h1
        className="text-glow text-5xl font-bold uppercase tracking-wide"
        style={{ opacity: s.h1, transform: 'translateY(' + (14 * (1 - s.h1)).toFixed(2) + 'px)' }}
      >
        {HEADLINE}
      </h1>

      <p
        className="mt-3 text-sm uppercase text-text-muted"
        style={{ opacity: s.sub, letterSpacing: (0.44 - 0.19 * s.sub).toFixed(3) + 'em' }}
      >
        {SUBLINE}
      </p>

      <div
        className="mt-[18px] flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.1em] text-text-muted"
        style={{ opacity: s.status }}
      >
        <span
          className="h-[7px] w-[7px] rounded-full bg-online"
          style={{ boxShadow: '0 0 8px oklch(72% 0.15 150 / 0.7)' }}
        />
        <span>{STATUSLINE}</span>
      </div>
    </div>
  );
}
