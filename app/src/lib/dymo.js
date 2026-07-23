// app/src/lib/dymo.js — thin async wrapper over the vendored framework.
let _fw = null;
let _loading = null;

function _inject(url) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = url;
    s.onload = resolve;
    s.onerror = () => reject(new Error('failed to load DYMO framework'));
    document.head.appendChild(s);
  });
}

async function fw() {
  if (_fw) return _fw;
  if (!_loading) {
    _loading = (async () => {
      if (!window.dymo?.label?.framework) {
        const { default: url } = await import('../vendor/dymo.connect.framework.js?url');
        await _inject(url);
      }
      const f = window.dymo.label.framework;
      await new Promise((res) => f.init(res));
      return f;
    })();
  }
  _fw = await _loading;
  return _fw;
}

export function resetDymo() {
  // Drop every cached layer (incl. the framework's own faulty-instance cache,
  // which only a fresh script evaluation can clear).
  _fw = null;
  _loading = null;
  try { delete window.dymo; } catch { window.dymo = undefined; }
}

export async function dymoReady() {
  try {
    const f = await fw();
    const env = f.checkEnvironment();
    const ok = !!(env && env.isBrowserSupported && env.isFrameworkInstalled);
    if (!ok) resetDymo();
    return ok;
  } catch {
    resetDymo();
    return false;
  }
}

export async function getPrinters() {
  const f = await fw();
  return f.getPrinters()
    .filter((p) => p.printerType === 'LabelWriterPrinter')
    .map((p) => p.name);
}

function applyValues(f, labelXml, values) {
  const label = f.openLabelXml(labelXml);
  for (const [name, val] of Object.entries(values)) {
    try { label.setObjectText(name, val ?? ''); } catch { /* absent object */ }
  }
  return label;
}

export async function renderPreview(labelXml, values) {
  const f = await fw();
  const label = applyValues(f, labelXml, values);
  return f.renderLabel(label.getLabelXml(), '', '');  // base64 PNG
}

export async function printMerge(printerName, labelXml, records) {
  const f = await fw();
  const set = new f.LabelSetBuilder();
  for (const rec of records) {
    const r = set.addRecord();
    for (const [name, val] of Object.entries(rec)) r.setText(name, val ?? '');
  }
  f.printLabel(printerName, '', labelXml, set.toString());
}
