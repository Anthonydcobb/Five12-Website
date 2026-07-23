// DYMO Connect "DesktopLabel" mail-merge done structurally.
//
// The legacy dymo.label.framework setObjectText / LabelSetBuilder do NOT
// replace text in the DesktopLabel format — they leave the box's existing
// <TextSpan> runs in place and append, producing doubled text. So for each
// named TextObject we collapse its text runs to a single run carrying the
// merge value, preserving the box's font. Boxes whose name is NOT in `values`
// are left untouched, so literal boxes (e.g. a "W" unit label) survive.

export function mergeLabel(labelXml, values) {
  const doc = new DOMParser().parseFromString(labelXml, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length) {
    throw new Error('Could not parse label XML');
  }
  const objects = doc.getElementsByTagName('TextObject');
  for (let i = 0; i < objects.length; i++) {
    const obj = objects[i];
    const name = directChildText(obj, 'Name');
    if (name == null || !Object.prototype.hasOwnProperty.call(values, name)) continue;
    setTextObjectText(doc, obj, values[name] == null ? '' : String(values[name]));
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

function setTextObjectText(doc, textObject, value) {
  const ft = firstChild(textObject, 'FormattedText');
  if (!ft) return; // unknown shape — skip rather than corrupt
  const lineSpans = [...ft.children].filter((c) => c.tagName === 'LineTextSpan');
  // Preserve the font from the first TextSpan that carries one.
  let fontInfo = null;
  for (const ls of lineSpans) {
    for (const ts of [...ls.children]) {
      if (ts.tagName === 'TextSpan') {
        const fi = firstChild(ts, 'FontInfo');
        if (fi) { fontInfo = fi.cloneNode(true); break; }
      }
    }
    if (fontInfo) break;
  }
  for (const ls of lineSpans) ft.removeChild(ls);
  const line = doc.createElement('LineTextSpan');
  const span = doc.createElement('TextSpan');
  const textEl = doc.createElement('Text');
  textEl.textContent = value;
  span.appendChild(textEl);
  if (fontInfo) span.appendChild(fontInfo);
  line.appendChild(span);
  ft.appendChild(line);
}
