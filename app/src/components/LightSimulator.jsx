// File: src/components/LightSimulator.jsx
import React, { useRef, useEffect, useState } from 'react';
import { computeEffect } from '../utils/effectMath';

export default function LightSimulator({ params }) {
  const [lightCount, setLightCount] = useState(5);
  const [cols, setCols] = useState(5);
  const [rows, setRows] = useState(1);
  const cellSize = 60;

  // Track each light's position
  const [positions, setPositions] = useState({});
  const containerRef = useRef(null);
  const draggingRef = useRef({ index: null, offsetX: 0, offsetY: 0 });

  // Initialize positions when lights, cols, or rows change
  useEffect(() => {
    const newPositions = {};
    Array.from({ length: lightCount }).forEach((_, i) => {
      const x = (i % cols) * cellSize;
      const y = Math.floor(i / cols) * cellSize;
      newPositions[i] = { x, y };
    });
    setPositions(newPositions);
  }, [lightCount, cols, rows]);

  // Animation loop for effect
  useEffect(() => {
    const start = performance.now();
    let frame;

    function animate() {
      const t = (performance.now() - start) / 1000;
      Object.entries(positions).forEach(([i, pos]) => {
        const el = containerRef.current.querySelector(`[data-index='${i}'] .light-circle`);
        if (!el) return;
        const phaseOff = params.offset + (360 / lightCount) * Number(i);
        const value = computeEffect(params.table, t, { ...params, offset: phaseOff });
        el.style.backgroundColor = `rgba(255, 204, 0, ${value})`;
        el.style.borderColor = `rgba(255, 204, 0, 1)`;
      });
      frame = requestAnimationFrame(animate);
    }
    animate();
    return () => cancelAnimationFrame(frame);
  }, [params, positions, lightCount]);

  // Pointer event handlers
  useEffect(() => {
    const handleMove = (e) => {
      const { index, offsetX, offsetY } = draggingRef.current;
      if (index === null) return;
      const rect = containerRef.current.getBoundingClientRect();
      let x = e.clientX - rect.left - offsetX;
      let y = e.clientY - rect.top - offsetY;
      x = Math.max(0, Math.min(x, cols * cellSize - cellSize));
      y = Math.max(0, Math.min(y, rows * cellSize - cellSize));
      setPositions((prev) => ({ ...prev, [index]: { x, y } }));
    };
    const handleUp = () => {
      draggingRef.current.index = null;
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerup', handleUp);
    };
    window.addEventListener('pointermove', handleMove);
    window.addEventListener('pointerup', handleUp);
    return () => {
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerup', handleUp);
    };
  }, [cols, rows]);

  const handlePointerDown = (e, i) => {
    const rect = e.target.getBoundingClientRect();
    draggingRef.current = {
      index: i,
      offsetX: e.clientX - rect.left,
      offsetY: e.clientY - rect.top,
    };
  };

  return (
    <div className="p-4">
      <div className="flex gap-4 mb-4">
        <label className="flex flex-col">
          Lights
          <input
            type="number"
            min="1"
            value={lightCount}
            onChange={(e) => setLightCount(Number(e.target.value) || 1)}
            className="border px-2 py-1 rounded"
          />
        </label>
        <label className="flex flex-col">
          Columns
          <input
            type="number"
            min="1"
            value={cols}
            onChange={(e) => setCols(Number(e.target.value) || 1)}
            className="border px-2 py-1 rounded"
          />
        </label>
        <label className="flex flex-col">
          Rows
          <input
            type="number"
            min="1"
            value={rows}
            onChange={(e) => setRows(Number(e.target.value) || 1)}
            className="border px-2 py-1 rounded"
          />
        </label>
      </div>

      <div
        ref={containerRef}
        className="relative"
        style={{
          width: cols * cellSize,
          height: rows * cellSize,
          border: '1px solid #ccc',
        }}
      >
        {Object.entries(positions).map(([i, pos]) => (
          <div
            key={i}
            data-index={i}
            className="absolute"
            style={{ left: pos.x, top: pos.y, width: cellSize, height: cellSize }}
            onPointerDown={(e) => handlePointerDown(e, Number(i))}
          >
            <div
              className="light-circle w-full h-full rounded-full border-2"
              style={{ backgroundColor: 'rgba(255,204,0,0)' }}
            >
              <span className="block text-center text-sm font-bold text-black">{Number(i) + 1}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
