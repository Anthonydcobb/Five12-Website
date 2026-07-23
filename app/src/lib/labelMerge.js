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

// Native DesktopLabel mail-merge. DYMO Connect labels can carry their own
// <DataTable> (columns + rows) with column-bound boxes (<DataMappingTextSpan>
// + <ColumnName>). Printing such a label emits ONE label per DataRow in a
// single continuous job — which is what avoids the per-job gap re-seek ("buzz")
// that printing one job per record causes. We rebuild the DataTable's rows from
// our records (each keyed by box/variable name) and set each bound box's preview
// <Text> to the first record, so the single-label render/preview is also correct.
//
// Returns null when the template is NOT a native-merge label (no <DataTable> or
// no column-bound boxes); the caller then falls back to per-record printing.
export function mergeLabelSet(labelXml, records) {
  if (!records || records.length === 0) return null;
  const doc = new DOMParser().parseFromString(labelXml, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length) {
    throw new Error('Could not parse label XML');
  }
  const dataTable = doc.getElementsByTagName('DataTable')[0];
  if (!dataTable) return null;
  const columnsEl = firstChild(dataTable, 'Columns');
  const rowsEl = firstChild(dataTable, 'Rows');
  if (!columnsEl || !rowsEl) return null;

  const columns = [...columnsEl.children]
    .filter((c) => c.tagName === 'DataColumn')
    .map((c) => (c.textContent || '').trim());
  if (!columns.length) return null;

  // column name -> the box (TextObject) name feeding it, read from each binding.
  const spans = doc.getElementsByTagName('DataMappingTextSpan');
  if (!spans.length) return null; // not a native-merge template
  const colToBox = {};
  for (let i = 0; i < spans.length; i++) {
    const col = directChildText(spans[i], 'ColumnName');
    const box = enclosingTextObjectName(spans[i]);
    if (col && box) colToBox[col] = box;
  }

  const cellFor = (rec, col) => {
    const box = colToBox[col];
    const v = box ? rec[box] : '';
    return v == null ? '' : String(v);
  };

  // Rebuild <Rows>: one <DataRow> per record, values in column order.
  while (rowsEl.firstChild) rowsEl.removeChild(rowsEl.firstChild);
  for (const rec of records) {
    const row = doc.createElement('DataRow');
    for (const col of columns) {
      const val = doc.createElement('Value');
      val.textContent = cellFor(rec, col);
      row.appendChild(val);
    }
    rowsEl.appendChild(row);
  }

  // Preview text = first record (renders/prints correctly even if a consumer
  // ignores the DataTable and falls back to the box's own text).
  const first = records[0];
  for (let i = 0; i < spans.length; i++) {
    const col = directChildText(spans[i], 'ColumnName');
    setSpanText(doc, spans[i], cellFor(first, col));
  }

  return new XMLSerializer().serializeToString(doc);
}

// Name of the TextObject that encloses a given descendant element (or null).
function enclosingTextObjectName(el) {
  let n = el.parentNode;
  while (n && n.tagName !== 'TextObject') n = n.parentNode;
  return n ? directChildText(n, 'Name') : null;
}

// Set a span's direct <Text> child (handles a self-closing <Text/> element).
function setSpanText(doc, span, value) {
  let textEl = firstChild(span, 'Text');
  if (!textEl) { textEl = doc.createElement('Text'); span.insertBefore(textEl, span.firstChild); }
  textEl.textContent = value;
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
