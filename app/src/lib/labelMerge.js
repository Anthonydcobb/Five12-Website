// DYMO Connect "DesktopLabel" mail-merge done structurally.
//
// The legacy dymo.label.framework setObjectText / LabelSetBuilder do NOT
// replace text in the DesktopLabel format — they leave the box's existing
// <TextSpan> runs in place and append, producing doubled text. So for each
// named TextObject we collapse its text runs to a single run carrying the
// merge value, preserving the box's font. Boxes whose name is NOT in `values`
// are left untouched, so literal boxes (e.g. a "W" unit label) survive.
//
// The DesktopLabel schema REQUIRES every <TextSpan> to carry a <FontInfo>, so
// the run we build always gets one: the box's own font if present, else a
// font borrowed from elsewhere in the label, else a synthesized default.
//
// There is no batch form of this. The DYMO Connect web service (1.6.1.7)
// rejects a PrintLabel/PrintLabel2 carrying ANY non-empty labelSetXml against a
// DesktopLabel with HTTP 400 "Error printing label. Exception: " — an empty
// exception detail — no matter how the set is shaped (framework-canonical
// LabelSetBuilder output, CDATA or plain text, with or without an XML
// declaration, box names with or without spaces). The same request with an
// empty labelSetXml returns 200. So callers merge one record per label and
// print one job per label; see printMerge in dymo.js.

export function mergeLabel(labelXml, values) {
  const doc = new DOMParser().parseFromString(labelXml, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length) {
    throw new Error('Could not parse label XML');
  }
  const fallbackFont = firstFontInfoInDoc(doc); // may be null
  const objects = doc.getElementsByTagName('TextObject');
  for (let i = 0; i < objects.length; i++) {
    const obj = objects[i];
    const name = directChildText(obj, 'Name');
    if (name == null || !Object.prototype.hasOwnProperty.call(values, name)) continue;
    setTextObjectText(doc, obj, values[name] == null ? '' : String(values[name]), fallbackFont);
  }
  clearDataRows(doc);
  return new XMLSerializer().serializeToString(doc);
}

// A template authored in DYMO Connect carries the rows it was authored against
// (ours ships 98). Those rows are a second, invisible answer to "how many labels
// come out" sitting behind the records the operator actually chose, so every
// label we hand to the service gets them cleared. The <DataTable> and its
// <Columns> stay: the boxes are bound to those column names.
function clearDataRows(doc) {
  const dataTable = doc.getElementsByTagName('DataTable')[0];
  if (!dataTable) return;
  const rowsEl = firstChild(dataTable, 'Rows');
  if (rowsEl) while (rowsEl.firstChild) rowsEl.removeChild(rowsEl.firstChild);
}

function directChildText(el, tag) {
  for (const c of el.children) if (c.tagName === tag) return (c.textContent || '').trim();
  return null;
}

function firstChild(el, tag) {
  for (const c of el.children) if (c.tagName === tag) return c;
  return null;
}

function firstFontInfoInDoc(doc) {
  const all = doc.getElementsByTagName('FontInfo');
  return all.length ? all[0] : null;
}

function fontInfoFromObject(textObject) {
  const ft = firstChild(textObject, 'FormattedText');
  if (!ft) return null;
  for (const ls of ft.children) {
    if (ls.tagName !== 'LineTextSpan') continue;
    for (const ts of ls.children) {
      if (ts.tagName === 'TextSpan') {
        const fi = firstChild(ts, 'FontInfo');
        if (fi) return fi;
      }
    }
  }
  return null;
}

// A minimal valid FontInfo, used only if the whole label somehow has none.
function synthFontInfo(doc) {
  const fi = doc.createElement('FontInfo');
  const add = (tag, text) => { const e = doc.createElement(tag); e.textContent = text; fi.appendChild(e); };
  add('FontName', 'Arial');
  add('FontSize', '12');
  add('IsBold', 'False');
  add('IsItalic', 'False');
  add('IsUnderline', 'False');
  return fi;
}

function setTextObjectText(doc, textObject, value, fallbackFont) {
  const ft = firstChild(textObject, 'FormattedText');
  if (!ft) return; // unknown shape — skip rather than corrupt
  // Font priority: this box's own font → any font in the label → synthesized.
  const source = fontInfoFromObject(textObject) || fallbackFont;
  const fontInfo = source ? source.cloneNode(true) : synthFontInfo(doc);

  for (const ls of [...ft.children].filter((c) => c.tagName === 'LineTextSpan')) {
    ft.removeChild(ls);
  }
  const line = doc.createElement('LineTextSpan');
  const span = doc.createElement('TextSpan');
  const textEl = doc.createElement('Text');
  textEl.textContent = value;
  span.appendChild(textEl);
  span.appendChild(fontInfo); // schema requires FontInfo on every TextSpan
  line.appendChild(span);
  ft.appendChild(line);
}
