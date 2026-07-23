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
  return new XMLSerializer().serializeToString(doc);
}

// Multi-record printing via a DYMO "LabelSet". One printLabel() call feeds every
// record to the printer as a SINGLE continuous job, so the LabelWriter never
// re-seeks the label gap between labels (the "buzz"/misregistration that printing
// one job per record causes). The DYMO web service iterates the <LabelRecord>s
// and merges each <ObjectData> into the like-named text object.
//
// IMPORTANT: the service APPENDS ObjectData onto whatever text the object already
// holds (the DesktopLabel doubled-text bug). So the label XML passed ALONGSIDE
// this set must have those boxes emptied first — printMerge does that with
// mergeLabel(labelXml, blanks) — turning append-onto-empty into just the value.
//
// `boxNames` are the TextObject names to fill; `records` are keyed by those names.
export function buildLabelSetXml(records, boxNames) {
  const cdata = (v) =>
    `<![CDATA[${String(v == null ? '' : v).replace(/]]>/g, ']]]]><![CDATA[>')}]]>`;
  const attr = (s) =>
    String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  const body = records.map((rec) =>
    '  <LabelRecord>\n' +
    boxNames.map((b) => `    <ObjectData Name="${attr(b)}">${cdata(rec[b])}</ObjectData>`).join('\n') +
    '\n  </LabelRecord>'
  ).join('\n');
  return `<?xml version="1.0" encoding="utf-8"?>\n<LabelSet>\n${body}\n</LabelSet>`;
}

// The label to send ALONGSIDE a LabelSet: every mapped box emptied (so the
// service's append-onto-existing-text can't double), and any embedded <DataTable>
// rows cleared so only the LabelSet drives how many labels print.
export function blankLabel(labelXml, boxNames) {
  const doc = new DOMParser().parseFromString(labelXml, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length) {
    throw new Error('Could not parse label XML');
  }
  const fallbackFont = firstFontInfoInDoc(doc);
  const wanted = new Set(boxNames);
  const objects = doc.getElementsByTagName('TextObject');
  for (let i = 0; i < objects.length; i++) {
    const name = directChildText(objects[i], 'Name');
    if (name != null && wanted.has(name)) setTextObjectText(doc, objects[i], '', fallbackFont);
  }
  const dataTable = doc.getElementsByTagName('DataTable')[0];
  if (dataTable) {
    const rowsEl = firstChild(dataTable, 'Rows');
    if (rowsEl) while (rowsEl.firstChild) rowsEl.removeChild(rowsEl.firstChild);
  }
  return new XMLSerializer().serializeToString(doc);
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
