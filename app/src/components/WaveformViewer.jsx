// File: src/components/WaveformViewer.jsx
import React, { useRef, useEffect } from 'react';
import { computeEffect } from '../utils/effectMath';

export default function WaveformViewer({ params, width = 400, height = 100 }) {
  const canvasRef = useRef();

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    let animationId;
    const startTime = performance.now();

    function draw() {
      const w = canvas.width;
      const h = canvas.height;
      const now = (performance.now() - startTime) / 1000;

      // Clear
      ctx.clearRect(0, 0, w, h);

      // Draw grid lines at 100%, 50%, 0%
      ctx.strokeStyle = '#4B5563';          // gray-600
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 2]);
      [0, h / 2, h].forEach((y) => {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      });
      ctx.setLineDash([]);

      // Draw waveform
      ctx.strokeStyle = '#0EA5E9';          // sky-600
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let x = 0; x <= w; x++) {
        const t = x / w;
        const value = computeEffect(
          params.table,
          now + t / (params.rate / 60),
          params
        );
        const y = h - value * h;
        x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.stroke();

      animationId = requestAnimationFrame(draw);
    }

    draw();
    return () => cancelAnimationFrame(animationId);
  }, [params]);

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      className="w-full bg-gray-800 rounded-lg mb-6 border border-gray-600"
    />
  );
}
