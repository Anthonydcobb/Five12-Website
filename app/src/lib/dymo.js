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
    .map((p) => ({ name: p.name, isTwinTurbo: !!p.isTwinTurbo }));
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

// One printLabel2 job per record, strictly sequenced: submit a label, poll its
// job until the printer says Finished, only then submit the next. The service
// returns from PrintLabel as soon as it ACCEPTS a job — not when the label
// finishes feeding — so firing jobs back-to-back makes the LabelWriter start a
// new job mid-feed and re-seek the label gap (the "buzz"/misregistration).
// Batching alternatives are ruled out by evidence: the service 400s on any
// non-empty labelSetXml (see labelMerge.js), and physical tests show the
// embedded DataTable never drives the label count.
//
// opts.roll ('Left'|'Right') is passed only for Twin Turbo printers — it pins
// the roll via LabelWriterPrintParams. opts.signal stops the run between
// labels (the service has no cancel endpoint, so the label in flight always
// completes). opts.onProgress fires after each label finishes.
const JOB_POLL_MS = 150;
const JOB_CEILING_MS = 15000;
const STATUS_FINISHED = 2; // dymo.label.framework.PrintJobStatus
const FAULT_REASONS = {
  3: 'Printer error',
  4: 'Paper out',
  [-1]: 'Processing error',
  [-2]: 'Printer busy',
};

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

// Resolve {fault: string|null} for one PrintJob. Finished → null fault.
// Error/PaperOut/ProcessingError/PrinterBusy → that reason. Printing/InQueue
// keep polling; Unknown/InvalidJobId/NotSpooled also keep polling (they appear
// transiently right after submit) — but the ceiling bounds the wait so a
// printer with unreliable status reporting paces the run instead of hanging
// it. An abort stops the WAIT (not the label) so Stop needn't outlast a slow
// label; the caller counts the label as printed either way.
async function awaitJobDone(job, signal) {
  const deadline = Date.now() + JOB_CEILING_MS;
  for (;;) {
    const info = await new Promise((res) => {
      try { job.getStatus(res); } catch (e) { res({ status: -1, statusMessage: String(e) }); }
    });
    const status = info ? info.status : 0;
    if (status === STATUS_FINISHED) return { fault: null };
    if (FAULT_REASONS[status] !== undefined) return { fault: FAULT_REASONS[status] };
    if (signal?.aborted) return { fault: null };
    if (Date.now() >= deadline) return { fault: null };
    await sleep(JOB_POLL_MS);
  }
}

export async function printMerge(printerName, labelXml, records, opts = {}) {
  const { roll, signal, onProgress } = opts;
  const f = await fw();
  const paramsXml = roll
    ? f.createLabelWriterPrintParamsXml({ copies: 1, twinTurboRoll: roll })
    : '';
  const total = records.length;
  let printed = 0;
  for (const rec of records) {
    if (signal?.aborted) return { printed, total, stopped: true, reason: null };
    const job = await f.printLabel2Async(printerName, paramsXml, mergeLabel(labelXml, rec), '');
    const { fault } = await awaitJobDone(job, signal);
    if (fault) return { printed, total, stopped: true, reason: fault };
    printed += 1;
    if (onProgress) onProgress({ printed, total });
  }
  return { printed, total, stopped: false, reason: null };
}
