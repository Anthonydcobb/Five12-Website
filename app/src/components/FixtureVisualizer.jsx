import React, { useRef, useEffect } from 'react';
import { computeEffect } from '../utils/effectMath';

const TRAIL_MAX = 180; // ~3 seconds at 60fps

export default function FixtureVisualizer({ fixtures, timeRef, masterRate, onUpdateBase }) {
  const canvasRef  = useRef(null);
  const rafRef     = useRef(null);
  const dragRef    = useRef(null);
  const trailsRef  = useRef({}); // { [fixtureId]: [{x,y},...] }

  // ─── Draw loop ────────────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const draw = () => {
      const W = canvas.width;
      const H = canvas.height;
      const t = timeRef.current;

      ctx.fillStyle = '#0a0f1a';
      ctx.fillRect(0, 0, W, H);

      // Subtle grid
      ctx.strokeStyle = '#111827';
      ctx.lineWidth = 1;
      for (let x = 0; x <= W; x += W / 4) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
      }
      for (let y = 0; y <= H; y += H / 4) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
      }

      // Center crosshair
      ctx.strokeStyle = '#1e3a5f';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(W / 2, 0); ctx.lineTo(W / 2, H); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke();
      ctx.setLineDash([]);

      fixtures.forEach((fix) => {
        const getVal = (pk, def) => {
          const base = fix.bases?.[pk] ?? def;
          const p = fix.params[pk];
          if (!p?.table) return base;
          const effectVal = computeEffect(p.table, t, { ...p, rate: (p.rate || 60) * masterRate });
          return Math.max(0, Math.min(1, base + (effectVal - 0.5)));
        };

        const intensity = getVal('intensity', 1.0);
        const pan       = getVal('pan',  0.5);
        const tilt      = getVal('tilt', 0.5);
        const r = getVal('red',   1.0);
        const g = getVal('green', 1.0);
        const b = getVal('blue',  1.0);

        const x = pan  * W;
        const y = tilt * H;

        const ri = Math.round(r * 255);
        const gi = Math.round(g * 255);
        const bi = Math.round(b * 255);

        const homeX = (fix.bases?.pan  ?? 0.5) * W;
        const homeY = (fix.bases?.tilt ?? 0.5) * H;
        const hasPanTiltFx = fix.params.pan?.table || fix.params.tilt?.table;

        // ── Trail ──────────────────────────────────────────────────────────
        if (!trailsRef.current[fix.id]) trailsRef.current[fix.id] = [];
        const trail = trailsRef.current[fix.id];
        if (hasPanTiltFx) {
          trail.push({ x, y });
          if (trail.length > TRAIL_MAX) trail.shift();
        } else if (trail.length) {
          trailsRef.current[fix.id] = [];
        }

        if (hasPanTiltFx && trail.length > 1) {
          for (let i = 1; i < trail.length; i++) {
            const p = i / trail.length;
            ctx.strokeStyle = `rgba(${ri},${gi},${bi},${(p * 0.5).toFixed(2)})`;
            ctx.lineWidth = p * 2.5;
            ctx.beginPath();
            ctx.moveTo(trail[i - 1].x, trail[i - 1].y);
            ctx.lineTo(trail[i].x, trail[i].y);
            ctx.stroke();
          }
        }

        // ── Home marker + leash ────────────────────────────────────────────
        if (hasPanTiltFx) {
          ctx.strokeStyle = 'rgba(250,204,21,0.2)';
          ctx.lineWidth = 1;
          ctx.setLineDash([2, 4]);
          ctx.beginPath();
          ctx.moveTo(homeX, homeY);
          ctx.lineTo(x, y);
          ctx.stroke();
          ctx.setLineDash([]);

          ctx.strokeStyle = 'rgba(250,204,21,0.55)';
          ctx.lineWidth = 1;
          const cs = 6;
          ctx.beginPath();
          ctx.moveTo(homeX - cs, homeY); ctx.lineTo(homeX + cs, homeY);
          ctx.moveTo(homeX, homeY - cs); ctx.lineTo(homeX, homeY + cs);
          ctx.stroke();
        }

        // ── Fixture off: dim ghost ─────────────────────────────────────────
        if (intensity < 0.02) {
          ctx.beginPath();
          ctx.arc(homeX, homeY, 5, 0, Math.PI * 2);
          ctx.strokeStyle = 'rgba(120,120,120,0.3)';
          ctx.lineWidth = 1;
          ctx.stroke();
          ctx.fillStyle = 'rgba(60,60,60,0.2)';
          ctx.fill();
          ctx.fillStyle = 'rgba(180,180,180,0.35)';
          ctx.font = 'bold 9px monospace';
          ctx.textAlign = 'center';
          ctx.fillText(`#${fix.id}`, homeX, homeY + 16);
          return;
        }

        // ── Fixture beam ───────────────────────────────────────────────────
        const baseRadius = 8;
        const radius = baseRadius + intensity * 10;
        const alpha  = intensity;

        const grd = ctx.createRadialGradient(x, y, 0, x, y, radius * 3);
        grd.addColorStop(0,   `rgba(${ri},${gi},${bi},${alpha * 0.6})`);
        grd.addColorStop(0.4, `rgba(${ri},${gi},${bi},${alpha * 0.2})`);
        grd.addColorStop(1,   `rgba(${ri},${gi},${bi},0)`);
        ctx.beginPath();
        ctx.arc(x, y, radius * 3, 0, Math.PI * 2);
        ctx.fillStyle = grd;
        ctx.fill();

        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${ri},${gi},${bi},${alpha})`;
        ctx.fill();

        if (intensity > 0.7) {
          ctx.beginPath();
          ctx.arc(x, y, radius * 0.35, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255,255,255,${(intensity - 0.7) * 2})`;
          ctx.fill();
        }

        ctx.fillStyle = 'rgba(255,255,255,0.55)';
        ctx.font = 'bold 9px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(`#${fix.id}`, x, y + radius + 11);
      });

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [fixtures, timeRef, masterRate]);

  // ─── Drag interaction ─────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const getPos = (e) => {
      const rect = canvas.getBoundingClientRect();
      return {
        x: (e.clientX - rect.left) * (canvas.width  / rect.width),
        y: (e.clientY - rect.top)  * (canvas.height / rect.height),
      };
    };

    // Hit-test against home (base) positions — that's what the user grabs to reposition
    const findFixture = ({ x, y }) => {
      const W = canvas.width, H = canvas.height;
      let hit = null, minDist = Infinity;
      fixtures.forEach(fix => {
        const fx = (fix.bases?.pan  ?? 0.5) * W;
        const fy = (fix.bases?.tilt ?? 0.5) * H;
        const d  = Math.hypot(x - fx, y - fy);
        if (d < 26 && d < minDist) { hit = fix; minDist = d; }
      });
      return hit;
    };

    const onDown = (e) => {
      const pos = getPos(e);
      const fix = findFixture(pos);
      if (fix) {
        dragRef.current = { fixtureId: fix.id };
        canvas.style.cursor = 'grabbing';
        e.preventDefault();
      }
    };

    const onMove = (e) => {
      const pos = getPos(e);
      if (dragRef.current) {
        const W = canvas.width, H = canvas.height;
        const pan  = Math.max(0, Math.min(1, pos.x / W));
        const tilt = Math.max(0, Math.min(1, pos.y / H));
        onUpdateBase(dragRef.current.fixtureId, pan, tilt);
      } else {
        canvas.style.cursor = findFixture(pos) ? 'grab' : 'crosshair';
      }
    };

    const onUp = () => {
      if (dragRef.current) {
        dragRef.current = null;
        canvas.style.cursor = 'crosshair';
      }
    };

    canvas.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup',   onUp);
    return () => {
      canvas.removeEventListener('mousedown', onDown);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup',   onUp);
    };
  }, [fixtures, onUpdateBase]);

  return (
    <canvas
      ref={canvasRef}
      width={300}
      height={300}
      className="w-full h-full rounded"
      style={{ cursor: 'crosshair' }}
    />
  );
}
