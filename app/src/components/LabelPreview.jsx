// File: src/components/LabelPreview.jsx

import React from 'react';

export default function LabelPreview({ templateConfig, size }) {
  // nothing to show if no fields
  if (!templateConfig?.fields?.length) return null;

  // --- 1) figure out your template's "real" dimensions
  const base = {
    '5161': { width: 450, height: 200 },
    '5163': { width: 450, height: 300 },
    '18294': { width:  64, height: 168 },
  }[size] || { width: 450, height: 150 };

  // --- 2) pick a thumbnail width and compute scale
  const THUMB_WIDTH = 80;             // your desired thumbnail width
  const scale       = THUMB_WIDTH / base.width;
  const thumbHeight = base.height * scale;

  // --- 3) wrapper that crops overflow at thumbnail size
  const wrapperStyle = {
    width:           THUMB_WIDTH,
    height:          thumbHeight,
    overflow:        'hidden',
    background:      '#fff',        // white background
    border:          '1px solid #666',
    position:        'relative',
  };

  // --- 4) inner container is the full-sized layout, simply scaled down
  const contentStyle = {
    width:           base.width,
    height:          base.height,
    transform:       `scale(${scale})`,
    transformOrigin: '0 0',
    position:        'relative',
  };

  return (
    <div style={wrapperStyle}>
      <div style={contentStyle}>
        {templateConfig.fields.map((fld, i) => {
          // absolute coords & size in unscaled space
          const common = {
            position:    'absolute',
            left:        fld.x,
            top:         fld.y,
            width:       fld.width,
            height:      fld.height,
            fontSize:    fld.fontSize,
            fontFamily:  fld.fontFamily,
            fontWeight:  fld.fontWeight,
            fontStyle:   fld.fontStyle,
            textDecoration: fld.textDecoration,
            color:       fld.color,
            display:     'flex',
            alignItems:  'center',
            justifyContent: fld.textAlign === 'right' ? 'flex-end' : fld.textAlign === 'center' ? 'center' : 'flex-start',
            pointerEvents:  'none',
          };

          // rectangles
          if (fld.key === 'rectangle') {
            return (
              <div
                key={i}
                style={{
                  ...common,
                  border: `${fld.strokeWidth}px solid ${fld.strokeColor}`,
                  background: fld.fillColor,
                }}
              />
            );
          }

          // lines
          if (fld.key === 'line') {
            return (
              <div
                key={i}
                style={{
                  position:        'absolute',
                  left:            fld.x,
                  top:             fld.y + fld.height / 2,
                  width:           fld.width,
                  height:          fld.strokeWidth,
                  backgroundColor: fld.strokeColor,
                  pointerEvents:   'none',
                }}
              />
            );
          }

          // text‐boxes or data fields
          const text =
            fld.key === 'text'
              ? fld.textValue || ''
              : `{{ ${fld.key} }}`;

          return (
            <div key={i} style={common}>
              <span>{text}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
