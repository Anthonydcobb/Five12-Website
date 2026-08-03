// app/src/lib/dymo.js — thin async wrapper over the vendored framework.
import { mergeLabel } from './labelMerge';

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

// Rejects on this DYMO Connect web service (1.6.1.7): its RenderLabel endpoint
// is broken outright, not just for our template. It answers HTTP 500 with an
// empty body for EVERY input — the stored template, a stock DLS 8.0
// DieCutLabel, a minimal DesktopLabel, and even no parameters at all — while
// PrintLabel accepts the same XML and returns 200. The Windows Application log
// names the cause: the handler throws before it reads the request.
//
//   System.IO.FileNotFoundException:
//   File name: 'System.Xml.XmlSerializer, Version=8.0.0.0, ...'
//      at DYMO.WebApi.Server.Controllers.DymoDLSSDKController.RenderLabel(...)
//
// i.e. the assembly is missing from DYMO's single-file bundle, so the endpoint
// cannot work at all in this build. Callers must surface the rejection rather
// than treat a missing preview as "not mapped yet" — see DymoPrintDialog.
export async function renderPreview(labelXml, values) {
  const f = await fw();
  return f.renderLabel(mergeLabel(labelXml, values), '', '');
}

// One printLabel() call per record, each carrying that record's values merged in.
//
// A LabelSet would batch all records into a single continuous job, but this DYMO
// Connect web service (1.6.1.7) answers ANY non-empty labelSetXml on a
// DesktopLabel with HTTP 400 "Error printing label. Exception: " — see the note
// in labelMerge.js for the shapes ruled out. Sending one merged label per job is
// the only form it accepts, so that is what we do.
export async function printMerge(printerName, labelXml, records) {
  const f = await fw();
  for (const rec of records) {
    f.printLabel(printerName, '', mergeLabel(labelXml, rec), '');
  }
}
