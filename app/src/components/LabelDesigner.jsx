// File: src/components/LabelDesigner.jsx

import React, { useState, useEffect, useRef } from 'react';
import { Rnd } from 'react-rnd';

// default data-fields
const DEFAULT_DATA_FIELDS = [
  'set','fixture','type','location',
  'notes','universe','address','weight','wattage','firmware'
];

// shape tools
const SHAPE_OPTIONS = [
  { key:'text',      label:'Text Box',  width:120, height:40, fontSize:16 },
  { key:'rectangle', label:'Rectangle', width:100, height:60, fontSize: 0 },
  { key:'line',      label:'Line',      width:120, height: 2, fontSize: 0 },
];

export default function LabelDesigner({
  templateConfig = { fields: [] },
  onConfigChange,
  dataFields    = DEFAULT_DATA_FIELDS,
  shapes        = SHAPE_OPTIONS,
  labelSize     = '5161',
  // the new preview props:
  previewActive = false,
  previewData   = {},          // { fixture_number: 101, ... }
  onPrev,                      // () => void
  onNext,                      // () => void
  previewIndex = 0,            // 0-based
  previewTotal = 0,
}) {
  const containerRef = useRef(null);
  const [config,    setConfig]    = useState({ fields: templateConfig.fields || [] });
  const [selectedIdx, setSelectedIdx] = useState(null);

  // sync when parent resets
  useEffect(() => {
    setConfig({ fields: templateConfig.fields || [] });
  }, [templateConfig]);

  function pushConfig(newCfg) {
    setConfig(newCfg);
    onConfigChange?.(newCfg);
  }

  // delete / escape
  useEffect(() => {
    const h = e => {
      if (e.key === 'Delete' && selectedIdx != null) removeField(selectedIdx);
      if (e.key === 'Escape')                setSelectedIdx(null);
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [selectedIdx, config.fields]);

  // sidebar drag
  function handleDragStart(e, key) {
    e.dataTransfer.setData('text/plain', key);
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setDragImage(e.target, 0, 0) } catch {}
  }
  function handleDragOver(e) { e.preventDefault() }
  function handleDrop(e) {
    e.preventDefault();
    const key  = e.dataTransfer.getData('text/plain');
    const rect = containerRef.current.getBoundingClientRect();
    addField(key, e.clientX - rect.left, e.clientY - rect.top);
  }

  function addField(key, x = 20, y = 20) {
    const shapeOpt = shapes.find(s => s.key === key);
    const isShape  = !!shapeOpt;
    const w        = isShape ? shapeOpt.width  : 140;
    const h        = isShape ? shapeOpt.height :  40;
    const fs       = isShape ? shapeOpt.fontSize:  14;
    const f = { key, x, y, width:w, height:h, fontSize:fs };

    // typography defaults
    if (!isShape || key==='text') {
      f.color          = '#000';
      f.fontFamily     = 'Arial';
      f.fontWeight     = 'normal';
      f.fontStyle      = 'normal';
      f.textDecoration = 'none';
      f.textAlign      = key === 'text' ? 'left' : 'center';
    }
    if (key==='text')      f.textValue = '';
    if (key==='rectangle') Object.assign(f, {
      strokeWidth:1, strokeColor:'#000', fillColor:'transparent'
    });
    if (key==='line')      Object.assign(f, {
      strokeWidth:1, strokeColor:'#000'
    });

    const arr = [...config.fields, f];
    pushConfig({ fields: arr });
    setSelectedIdx(arr.length-1);
  }

  function updateField(i, changes) {
    const arr = config.fields.map((fld,j) =>
      j===i ? { ...fld, ...changes } : fld
    );
    pushConfig({ fields: arr });
  }

  function removeField(i) {
    const arr = config.fields.filter((_,j) => j!==i);
    pushConfig({ fields: arr });
    setSelectedIdx(null);
  }

  // canvas sizing (inches→px→scale)
  const inchSizes = {
    '5160':  { w:2.625, h:1.0    }, '8160':  { w:2.625, h:1.0    },
    '5161':  { w:4.0,   h:1.0    },
    '5162':  { w:4.0,   h:1.3333 },
    '5163':  { w:4.0,   h:2.0    }, '8163':  { w:4.0,   h:2.0    },
    '5164':  { w:4.0,   h:3.3333 }, '8164':  { w:4.0,   h:3.3333 },
    '5167':  { w:1.75,  h:0.5    }, '8167':  { w:1.75,  h:0.5    },
    '5168':  { w:3.5,   h:5.0    },
    '5195':  { w:1.75,  h:0.6667 }, '18294': { w:1.75,  h:0.6667 },
  }[labelSize] || { w:4, h:1 };

  const DPI   = 72;
  const scale = 1.8;
  const canvasDims = {
    width:  inchSizes.w * DPI * scale,
    height: inchSizes.h * DPI * scale
  };

  const sel = selectedIdx != null ? config.fields[selectedIdx] : null;

  return (
    <div className="flex h-full bg-bg text-white">
      {/* ── Sidebar ───────────────────────────────────────────── */}
      <div className="w-1/5 bg-surface p-4 overflow-auto">
        <h3 className="font-semibold mb-3">Tools</h3>
        <h4 className="font-semibold mb-2">Shapes</h4>
        <ul className="space-y-2 mb-6">
          {shapes.map(s => (
            <li key={s.key}>
              <div
                draggable
                onDragStart={e=>handleDragStart(e,s.key)}
                className="cursor-move px-2 py-1 bg-surface-2 hover:bg-border rounded"
              >{s.label}</div>
            </li>
          ))}
        </ul>
        <h4 className="font-semibold mb-2">Data Fields</h4>
        <ul className="space-y-2">
          {dataFields.map(f => (
            <li key={f}>
              <div
                draggable
                onDragStart={e=>handleDragStart(e,f)}
                className="cursor-move px-2 py-1 bg-surface-2 hover:bg-border rounded"
              >{f.replace(/_/g,' ')}</div>
            </li>
          ))}
        </ul>
      </div>

      {/* ── Canvas + Toolbar ───────────────────────────────────── */}
      <div className="flex-1 flex flex-col">

        {/* ── Toolbar ─────────────────────────────────────────── */}
        <div
          className="h-12 flex items-center bg-surface px-4 border-b border-border"
          onMouseDown={e=>e.stopPropagation()}
        >
          {sel ? (
            sel.key==='rectangle' ? (
              <>
                <label className="text-sm">
                  Stroke W:
                  <input type="number" min="0"
                    className="ml-2 w-12 bg-surface-2 text-white p-1 rounded"
                    value={sel.strokeWidth}
                    onChange={e=>updateField(selectedIdx,{strokeWidth:+e.target.value})}
                  />
                </label>
                <label className="text-sm ml-4">
                  Stroke C:
                  <input type="color"
                    className="ml-2"
                    value={sel.strokeColor}
                    onChange={e=>updateField(selectedIdx,{strokeColor:e.target.value})}
                  />
                </label>
                <label className="text-sm ml-4">
                  Fill:
                  <input type="color"
                    className="ml-2"
                    value={sel.fillColor}
                    onChange={e=>updateField(selectedIdx,{fillColor:e.target.value})}
                  />
                </label>
              </>
            ) : sel.key==='line' ? (
              <>
                <label className="text-sm">
                  Width:
                  <input type="number" min="1"
                    className="ml-2 w-12 bg-surface-2 text-white p-1 rounded"
                    value={sel.strokeWidth}
                    onChange={e=>updateField(selectedIdx,{strokeWidth:+e.target.value})}
                  />
                </label>
                <label className="text-sm ml-4">
                  Color:
                  <input type="color"
                    className="ml-2"
                    value={sel.strokeColor}
                    onChange={e=>updateField(selectedIdx,{strokeColor:e.target.value})}
                  />
                </label>
              </>
            ) : (
              <>
                {/* Bold */}
                <button
                  onClick={()=>updateField(selectedIdx,{
                    fontWeight: sel.fontWeight==='bold'?'normal':'bold'
                  })}
                  className={`px-2 py-1 font-bold rounded ${
                    sel.fontWeight==='bold'?'bg-border':''}`}
                >B</button>
                {/* Italic */}
                <button
                  onClick={()=>updateField(selectedIdx,{
                    fontStyle: sel.fontStyle==='italic'?'normal':'italic'
                  })}
                  className={`px-2 py-1 italic rounded ml-2 ${
                    sel.fontStyle==='italic'?'bg-border':''}`}
                >I</button>
                {/* Underline */}
                <button
                  onClick={()=>updateField(selectedIdx,{
                    textDecoration:
                      sel.textDecoration==='underline'?'none':'underline'
                  })}
                  className={`px-2 py-1 underline rounded ml-2 ${
                    sel.textDecoration==='underline'?'bg-border':''}`}
                >U</button>

                <label className="text-sm ml-4">
                  Size:
                  <input type="number" min="1"
                    className="ml-2 w-16 bg-surface-2 text-white p-1 rounded"
                    value={sel.fontSize}
                    onChange={e=>updateField(selectedIdx,{fontSize:+e.target.value})}
                  />
                </label>

                <label className="text-sm ml-4">
                  Color:
                  <input type="color"
                    className="ml-2"
                    value={sel.color}
                    onChange={e=>updateField(selectedIdx,{color:e.target.value})}
                  />
                </label>

                <label className="text-sm ml-4">
                  Font:
                  <select
                    className="ml-2 bg-surface-2 text-white p-1 rounded"
                    value={sel.fontFamily}
                    onChange={e=>updateField(selectedIdx,{fontFamily:e.target.value})}
                  >
                    <option>Arial</option>
                    <option>Helvetica</option>
                    <option>Times New Roman</option>
                    <option>Verdana</option>
                    <option>Courier New</option>
                    <option>Georgia</option>
                  </select>
                </label>
                <div className="ml-4 flex gap-0.5">
                  {['left','center','right'].map(a => (
                    <button
                      key={a}
                      onClick={()=>updateField(selectedIdx,{textAlign:a})}
                      title={a}
                      className={`px-2 py-1 rounded text-xs ${sel.textAlign===a?'bg-border':'bg-surface-2 hover:bg-border'}`}
                    >
                      {a==='left'?'⬅':a==='center'?'⬛':'➡'}
                    </button>
                  ))}
                </div>
              </>
            )
          ) : (
            <span className="text-text-muted italic">
              Select an element to edit its properties
            </span>
          )}

          {sel && (
            <button
              onClick={()=>setSelectedIdx(null)}
              className="ml-auto bg-surface-2 hover:bg-border px-2 py-1 rounded text-sm"
            >
              Deselect
            </button>
          )}
        </div>

        {/* ── Canvas Container ───────────────────────────────────── */}
        <div className="relative flex-1 flex justify-center items-center p-4">
          <div
            ref={containerRef}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            style={{
              width:  canvasDims.width,
              height: canvasDims.height,
              backgroundColor: '#fff',
              border: '1px solid rgba(0,0,0,0.15)',
              borderRadius: '8px',
              boxShadow: `
                inset 0 0 0 1px rgba(0,0,0,0.05),
                0 4px 12px rgba(0,0,0,0.1)
              `
            }}
          >
            {/* inline preview arrows */}
            {previewActive && previewTotal > 1 && (
              <div className="absolute top-2 right-2 z-20 flex space-x-2">
                <button
                  onClick={onPrev}
                  disabled={previewIndex === 0}
                  className="px-2 py-1 bg-surface-2 text-white rounded disabled:opacity-50"
                >◀</button>
                <button
                  onClick={onNext}
                  disabled={previewIndex === previewTotal-1}
                  className="px-2 py-1 bg-surface-2 text-white rounded disabled:opacity-50"
                >▶</button>
              </div>
            )}
            {/* grid */}
            <div
              className="absolute inset-0 pointer-events-none"
              style={{
                backgroundImage: `
                  linear-gradient(to right, rgba(0,0,0,0.05) 1px,transparent 1px),
                  linear-gradient(to bottom, rgba(0,0,0,0.05) 1px,transparent 1px)
                `,
                backgroundSize: '20px 20px',
              }}
            />
            {/* fields */}
            {config.fields.map((fld, idx) => {
              const isText = fld.key==='text';
              const isData = !isText && fld.key!=='rectangle' && fld.key!=='line';

              return (
                <Rnd
                  key={`${fld.key}-${idx}`}
                  size={{ width: fld.width, height: fld.height }}
                  position={{ x: fld.x, y: fld.y }}
                  bounds="parent"
                  cancel=".text-input"
                  dragHandleClassName={isText?'drag-handle':''}
                  onDragStart={()=>setSelectedIdx(idx)}
                  onClick={e=>{e.stopPropagation();setSelectedIdx(idx)}}
                  onDragStop={(_,d)=>updateField(idx,{x:d.x,y:d.y})}
                  onResizeStop={(_,__,ref,___,pos)=>
                    updateField(idx,{
                      width:   parseInt(ref.style.width,10),
                      height:  parseInt(ref.style.height,10),
                      x:       pos.x,
                      y:       pos.y
                    })
                  }
                  style={{
                    zIndex:       selectedIdx===idx?20:10,
                    background:   'transparent',
                    border:       selectedIdx===idx?'2px solid #4C51BF':'none',
                    borderRadius: '4px',
                    padding:      isText?0:'4px',
                    cursor:       isText?'default':'move'
                  }}
                >
                  <div className="relative w-full h-full flex items-center" style={{justifyContent: fld.textAlign==='right'?'flex-end':fld.textAlign==='center'?'center':'flex-start'}}>
                    {/* line */}
                    {fld.key==='line' && (
                      <div className="w-full"
                        style={{
                          height:           fld.strokeWidth,
                          backgroundColor: fld.strokeColor
                        }}
                      />
                    )}
                    {/* rectangle */}
                    {fld.key==='rectangle' && (
                      <div className="w-full h-full rounded"
                        style={{
                          borderWidth:    fld.strokeWidth,
                          borderColor:    fld.strokeColor,
                          backgroundColor: fld.fillColor
                        }}
                      />
                    )}
                    {/* free text */}
                    {isText && (
                      <input
                        type="text"
                        className="text-input w-full h-full bg-transparent px-1 pr-6 outline-none"
                        value={fld.textValue}
                        onChange={e=>updateField(idx,{textValue:e.target.value})}
                        onFocus={()=>setSelectedIdx(idx)}
                        style={{
                          color:           fld.color,
                          fontFamily:      fld.fontFamily,
                          fontSize:        fld.fontSize,
                          fontWeight:      fld.fontWeight,
                          fontStyle:       fld.fontStyle,
                          textDecoration:  fld.textDecoration,
                          textAlign:       fld.textAlign || 'left',
                        }}
                      />
                    )}
                    {/* data field */}
                    {isData && (
                      <span className="truncate max-w-full"
                        style={{
                          color:           fld.color,
                          fontFamily:      fld.fontFamily,
                          fontSize:        fld.fontSize,
                          fontWeight:      fld.fontWeight,
                          fontStyle:       fld.fontStyle,
                          textDecoration:  fld.textDecoration
                        }}
                      >
                        {previewActive
                          ? (previewData[fld.key] ?? '')
                          : `{{ ${fld.key.replace(/_/g,' ')} }}`
                        }
                      </span>
                    )}
                    {/* drag‐handle */}
                    {isText && selectedIdx===idx && (
                      <div className="drag-handle absolute top-1 right-1 w-4 h-4 bg-border rounded cursor-move z-30" />
                    )}
                    {/* delete */}
                    {selectedIdx===idx && (
                      <button
                        onClick={()=>removeField(idx)}
                        className="absolute top-1 left-1 text-brand-hi font-bold"
                      >×</button>
                    )}
                  </div>
                </Rnd>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
