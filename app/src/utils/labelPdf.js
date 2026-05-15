import jsPDF from 'jspdf';

// Designer canvas: DPI=72, scale=1.8 → 1 canvas px = 1/1.8 PDF points
const SCALE = 1.8;

const FONT_MAP = {
  'Arial':           'helvetica',
  'Helvetica':       'helvetica',
  'Times New Roman': 'times',
  'Verdana':         'helvetica',
  'Courier New':     'courier',
  'Georgia':         'times',
};

// ─── Verified Avery specs (all measurements in inches) ───────────────────────
// Verified by back-calculation: cols×labelW + (cols-1)×gutterH + 2×marginLeft = 8.5"
//                               rows×labelH + 2×marginTop = 11"
export const AVERY = {
  // Address labels
  '5160':  { label:'Avery 5160',  dims:'1" × 2⅝"',     perSheet:30, cols:2, rows:10, labelW:2.625,  labelH:1.0,     marginTop:0.500,  marginLeft:0.1875,  gutterH:0.125,  gutterV:0 },
  '8160':  { label:'Avery 8160',  dims:'1" × 2⅝"',     perSheet:30, cols:3, rows:10, labelW:2.625,  labelH:1.0,     marginTop:0.500,  marginLeft:0.1875,  gutterH:0.125,  gutterV:0 },
  '5161':  { label:'Avery 5161',  dims:'1" × 4"',       perSheet:20, cols:2, rows:10, labelW:4.0,    labelH:1.0,     marginTop:0.500,  marginLeft:0.15625, gutterH:0.1875, gutterV:0 },
  '5162':  { label:'Avery 5162',  dims:'1⅓" × 4"',     perSheet:14, cols:2, rows:7,  labelW:4.0,    labelH:1.3333,  marginTop:0.844,  marginLeft:0.15625, gutterH:0.1875, gutterV:0 },
  '5163':  { label:'Avery 5163',  dims:'2" × 4"',       perSheet:10, cols:2, rows:5,  labelW:4.0,    labelH:2.0,     marginTop:0.500,  marginLeft:0.15625, gutterH:0.1875, gutterV:0 },
  '8163':  { label:'Avery 8163',  dims:'2" × 4"',       perSheet:10, cols:2, rows:5,  labelW:4.0,    labelH:2.0,     marginTop:0.500,  marginLeft:0.15625, gutterH:0.1875, gutterV:0 },
  '5164':  { label:'Avery 5164',  dims:'3⅓" × 4"',     perSheet:6,  cols:2, rows:3,  labelW:4.0,    labelH:3.3333,  marginTop:0.500,  marginLeft:0.15625, gutterH:0.1875, gutterV:0 },
  '8164':  { label:'Avery 8164',  dims:'3⅓" × 4"',     perSheet:6,  cols:2, rows:3,  labelW:4.0,    labelH:3.3333,  marginTop:0.500,  marginLeft:0.15625, gutterH:0.1875, gutterV:0 },
  // Return address / small
  '5167':  { label:'Avery 5167',  dims:'½" × 1¾"',     perSheet:80, cols:4, rows:20, labelW:1.75,   labelH:0.5,     marginTop:0.500,  marginLeft:0.300,   gutterH:0.300,  gutterV:0 },
  '8167':  { label:'Avery 8167',  dims:'½" × 1¾"',     perSheet:80, cols:4, rows:20, labelW:1.75,   labelH:0.5,     marginTop:0.500,  marginLeft:0.300,   gutterH:0.300,  gutterV:0 },
  '5195':  { label:'Avery 5195',  dims:'⅔" × 1¾"',     perSheet:60, cols:4, rows:15, labelW:1.75,   labelH:0.6667,  marginTop:0.500,  marginLeft:0.300,   gutterH:0.300,  gutterV:0 },
  '18294': { label:'Avery 18294', dims:'⅔" × 1¾"',     perSheet:60, cols:4, rows:15, labelW:1.75,   labelH:0.6667,  marginTop:0.500,  marginLeft:0.300,   gutterH:0.300,  gutterV:0 },
  // Shipping
  '5168':  { label:'Avery 5168',  dims:'3½" × 5"',     perSheet:4,  cols:2, rows:2,  labelW:3.5,    labelH:5.0,     marginTop:0.500,  marginLeft:0.500,   gutterH:0.500,  gutterV:0 },
};

// ─── Helper: hex color → [r, g, b] ──────────────────────────────────────────
function hexToRgb(hex = '#000000') {
  const h = hex.replace('#', '').padEnd(6, '0');
  return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)];
}

// ─── Draw one label at (originX, originY) in PDF points ─────────────────────
function drawLabel(doc, fields, rowData, originX, originY) {
  for (const fld of fields) {
    const x = originX + fld.x / SCALE;
    const y = originY + fld.y / SCALE;
    const w = fld.width  / SCALE;
    const h = fld.height / SCALE;

    if (fld.key === 'line') {
      const [r,g,b] = hexToRgb(fld.strokeColor);
      doc.setDrawColor(r,g,b);
      doc.setLineWidth((fld.strokeWidth || 1) / SCALE);
      doc.line(x, y + h/2, x + w, y + h/2);

    } else if (fld.key === 'rectangle') {
      const [sr,sg,sb] = hexToRgb(fld.strokeColor);
      doc.setDrawColor(sr,sg,sb);
      doc.setLineWidth((fld.strokeWidth || 1) / SCALE);
      const hasFill = fld.fillColor && fld.fillColor !== 'transparent';
      if (hasFill) {
        const [fr,fg,fb] = hexToRgb(fld.fillColor);
        doc.setFillColor(fr,fg,fb);
        doc.rect(x, y, w, h, 'FD');
      } else {
        doc.rect(x, y, w, h, 'S');
      }

    } else {
      // text box or data field
      const value = fld.key === 'text'
        ? (fld.textValue || '')
        : String(rowData?.[fld.key] ?? '');
      if (!value) continue;

      const fontSize = (fld.fontSize || 12) / SCALE;
      doc.setFontSize(fontSize);

      const [cr,cg,cb] = hexToRgb(fld.color || '#000000');
      doc.setTextColor(cr,cg,cb);

      const font = FONT_MAP[fld.fontFamily] || 'helvetica';
      let style = 'normal';
      if (fld.fontWeight === 'bold' && fld.fontStyle === 'italic') style = 'bolditalic';
      else if (fld.fontWeight === 'bold') style = 'bold';
      else if (fld.fontStyle === 'italic') style = 'italic';
      doc.setFont(font, style);

      const align = fld.textAlign || 'left';
      const textX = align === 'center' ? x + w/2 : align === 'right' ? x + w : x;
      doc.text(value, textX, y + h/2, { align, baseline: 'middle', maxWidth: w });
    }
  }
}

// ─── Main export ─────────────────────────────────────────────────────────────
export function generateLabelsPDF(templateConfig, rows, labelSize) {
  const spec = AVERY[labelSize];
  if (!spec) throw new Error(`Unsupported label size: ${labelSize}`);

  const { cols, rows: rowsPerPage, labelW, labelH, marginTop, marginLeft, gutterH, gutterV } = spec;
  const PT = 72; // points per inch
  const labelsPerPage = cols * rowsPerPage;

  const doc = new jsPDF({ unit: 'pt', format: 'letter', orientation: 'portrait' });

  rows.forEach((rowData, i) => {
    if (i > 0 && i % labelsPerPage === 0) doc.addPage();
    const pos     = i % labelsPerPage;
    const col     = pos % cols;
    const row     = Math.floor(pos / cols);
    const originX = (marginLeft + col * (labelW + gutterH)) * PT;
    const originY = (marginTop  + row * (labelH + gutterV)) * PT;
    drawLabel(doc, templateConfig.fields || [], rowData, originX, originY);
  });

  return doc;
}
