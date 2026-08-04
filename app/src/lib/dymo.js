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

// Can reject even when DYMO Connect looks healthy, so callers must surface the
// failure rather than treat a missing preview as "not mapped yet" — see
// DymoPrintDialog.
//
// History worth keeping: RenderLabel answered HTTP 500 with an empty body for
// EVERY input for an entire session — stored template, minimal DesktopLabel,
// even no parameters — while PrintLabel accepted the same XML and returned 200.
// The Windows Application log showed the handler throwing before it read the
// request (System.IO.FileNotFoundException on 'System.Xml.XmlSerializer'),
// which we misread as the assembly being absent from DYMO's single-file bundle,
// i.e. permanently broken in 1.6.1.7. It is not. The DYMO.WebApi.Win.Host
// process had gone bad; it later died outright, and a freshly started host
// renders the same template to a PNG on the first try. So: a 500 here means
// RESTART THE HOST (DYMO.WebApi.Win.Host.exe, or quit and relaunch DYMO
// Connect), not that previews are unsupported.
export async function renderPreview(labelXml, values) {
  const f = await fw();
  return f.renderLabel(mergeLabel(labelXml, values), '', '');
}

// One printLabelAsync job per record, strictly sequenced: submit a label,
// wait for the printer's queue to fully drain, only then submit the next.
// The service returns from PrintLabel as soon as it ACCEPTS a job — not when
// the label finishes feeding — so firing jobs back-to-back makes the
// LabelWriter start a new job mid-feed and re-seek the label gap (the
// "buzz"/misregistration). Batching alternatives are ruled out by evidence:
// the service 400s on any non-empty labelSetXml (see labelMerge.js), and
// physical tests show the embedded DataTable never drives the label count.
//
// Status is NOT sourced from the DYMO service — on DYMO Connect 1.6.1.7 that
// path does not exist: the vendored DlsWebService has no getJobStatus method
// (framework.job.getStatus() always answers Unknown/"not implemented"),
// PrintLabel2 returns `true` rather than a job id, and the service's
// GetJobStatus HTTP endpoint 404s identically to a nonexistent route. So we
// submit with the simpler printLabelAsync (its return value is unused —
// PrintLabel2's "job id" was never usable either) and read status from the
// Windows print spooler instead, via the backend's GET /api/print-queue.
// DYMO jobs verifiably land in the spooler under the same printer name and
// drain in ~1.8s.
//
// opts.roll ('Left'|'Right') is passed only for Twin Turbo printers — it pins
// the roll via LabelWriterPrintParams. opts.signal stops the run between
// labels (the service has no cancel endpoint, so the label in flight always
// completes). opts.onProgress fires after each label finishes.
const QUEUE_POLL_MS = 400;
const APPEAR_GRACE_MS = 2000;
const JOB_CEILING_MS = 15000;

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

async function fetchQueue(printerName) {
  const res = await fetch(`/api/print-queue?printer=${encodeURIComponent(printerName)}`);
  if (!res.ok) throw new Error(`print-queue request failed (${res.status})`);
  return res.json();
}

function faultFrom(q) {
  const ps = q.printerStatus || '';
  if (/PaperOut|PaperProblem|PaperJam/.test(ps)) return 'Paper out';
  if (/Error|Offline/.test(ps)) return 'Printer error';
  if ((q.jobs || []).some((j) => /Error/.test(j.status || ''))) return 'Printer error';
  return null;
}

// Wait for one submitted label to leave the spooler queue, reading status
// from the backend's spooler probe rather than the (nonexistent) DYMO job
// status. Two phases: APPEAR (the job may not have reached the spooler yet —
// a brief service-ACK-to-spooler race — so wait up to APPEAR_GRACE_MS for
// jobCount > 0, then proceed regardless in case it already drained between
// polls) and DRAIN (poll until jobCount === 0). A fetch rejection or non-200
// response is treated as a transient backend hiccup and just keeps polling,
// subject to the overall ceiling — it must never abort the run. An abort
// stops the WAIT (not the label) so Stop needn't outlast a slow label; the
// caller counts the label as printed either way.
async function awaitQueueDrain(printerName, signal) {
  const deadline = Date.now() + JOB_CEILING_MS;
  const appearDeadline = Date.now() + APPEAR_GRACE_MS;

  // Phase 1: APPEAR
  for (;;) {
    if (signal?.aborted) return { fault: null };
    if (Date.now() >= deadline) return { fault: null };
    let q;
    try { q = await fetchQueue(printerName); } catch { q = null; }
    if (q) {
      const fault = faultFrom(q);
      if (fault) return { fault };
      if (q.jobCount > 0) break;
    }
    if (Date.now() >= appearDeadline) break; // proceed regardless — may have already drained
    await sleep(QUEUE_POLL_MS);
  }

  // Phase 2: DRAIN
  for (;;) {
    if (signal?.aborted) return { fault: null };
    if (Date.now() >= deadline) return { fault: null };
    let q;
    try { q = await fetchQueue(printerName); } catch { q = null; }
    if (q) {
      const fault = faultFrom(q);
      if (fault) return { fault };
      if (q.jobCount === 0) return { fault: null };
    }
    await sleep(QUEUE_POLL_MS);
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
    await f.printLabelAsync(printerName, paramsXml, mergeLabel(labelXml, rec), '');
    const { fault } = await awaitQueueDrain(printerName, signal);
    if (fault) return { printed, total, stopped: true, reason: fault };
    printed += 1;
    if (onProgress) onProgress({ printed, total });
  }
  return { printed, total, stopped: false, reason: null };
}
