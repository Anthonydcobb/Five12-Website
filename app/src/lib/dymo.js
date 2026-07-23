// app/src/lib/dymo.js — thin async wrapper over the vendored framework.
let _fw = null;

async function fw() {
  if (_fw) return _fw;
  await import('../vendor/dymo.connect.framework.js'); // attaches window.dymo
  const f = window.dymo.label.framework;
  await new Promise((res) => f.init(res));
  _fw = f;
  return f;
}

export async function dymoReady() {
  try {
    const f = await fw();
    const env = f.checkEnvironment();
    return !!(env && env.isBrowserSupported && env.isFrameworkInstalled);
  } catch { return false; }
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
