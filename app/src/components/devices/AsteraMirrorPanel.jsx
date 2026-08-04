import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';

const STATUS_MS = 3000;
// Gap between captures, measured from the completion of the previous one.
// On the SM-T290 a screencap round-trip is 514-644 ms (mean 529), so anything
// below that guarantees a backlog. 750 leaves headroom without feeling slower
// than the ~1.9 fps the device can actually deliver.
const FRAME_MS = 750;
const STALE_AFTER_SEC = 3;
const TAP_SLOP_PX = 8;
// How long a failed-input message stays on screen before it auto-clears.
// Long enough to read, short enough not to linger as permanent clutter if
// the operator doesn't immediately retry. It's also cleared early — before
// this fires — by the next *successful* input.
const INPUT_ERROR_MS = 5000;

// axios delivers the *error* response body as a Blob too when the request
// was made with responseType: 'blob', so err.response.data is a Blob, not
// the parsed JSON. Read it as text and parse out {"reason": "..."}. Never
// throw — a malformed or empty body just falls back to the generic message.
async function frameErrorReason(err) {
  const data = err?.response?.data;
  if (data instanceof Blob) {
    try {
      const text = await data.text();
      const parsed = JSON.parse(text);
      return parsed?.reason || 'frame unavailable';
    } catch {
      return 'frame unavailable';
    }
  }
  return data?.reason || 'frame unavailable';
}

export default function AsteraMirrorPanel() {
  const [status, setStatus] = useState(null);
  const [frameUrl, setFrameUrl] = useState(null);
  const [frameError, setFrameError] = useState(null);
  // Kept separate from frameError: the frame-poll effect below writes
  // frameError on every tick (~750ms), which would wipe out an input
  // failure before the operator had a chance to read it.
  const [inputError, setInputError] = useState(null);
  const urlRef = useRef(null);
  const generationRef = useRef(0);
  const inputErrorTimerRef = useRef(null);

  useEffect(() => () => {
    if (inputErrorTimerRef.current) clearTimeout(inputErrorTimerRef.current);
  }, []);

  const pollStatus = useCallback(async () => {
    try {
      const { data } = await axios.get('/api/devices/astera/status');
      setStatus(data);
    } catch {
      setStatus({ available: false, disabled: false, reason: 'backend unreachable' });
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = async () => { if (alive) await pollStatus(); };
    tick();
    const i = setInterval(tick, STATUS_MS);
    return () => { alive = false; clearInterval(i); };
  }, [pollStatus]);

  const live = status?.available === true;

  useEffect(() => {
    if (!live) return undefined;
    let alive = true;
    let timer = null;
    const grab = async () => {
      const generation = ++generationRef.current;
      try {
        const resp = await axios.get('/api/devices/astera/frame',
                                     { responseType: 'blob' });
        if (!alive) return;
        if (generation !== generationRef.current) {
          // A later request already resolved and is now displayed; this
          // result is stale. We haven't created an object URL for it yet,
          // so there is nothing to revoke but the currently displayed one
          // — leave it alone and drop this frame silently.
          return;
        }
        const next = URL.createObjectURL(resp.data);
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = next;
        setFrameUrl(next);
        setFrameError(null);
      } catch (err) {
        if (alive && generation === generationRef.current) {
          setFrameError(await frameErrorReason(err));
        }
      } finally {
        // Chain from completion rather than firing on a fixed interval. A
        // capture routinely outlives any interval short enough to feel live,
        // and setInterval would stack a new request on top of every one still
        // in flight until the backlog took the panel down with it.
        if (alive) timer = setTimeout(grab, FRAME_MS);
      }
    };
    grab();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
      if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = null; }
    };
  }, [live]);

  const reconnect = async () => { await pollStatus(); };

  const imgRef = useRef(null);
  const downRef = useRef(null);

  const toDevice = (e) => {
    const el = imgRef.current;
    if (!el || !status?.screenW || !status?.screenH) return null;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    const x = Math.round(((e.clientX - r.left) / r.width) * status.screenW);
    const y = Math.round(((e.clientY - r.top) / r.height) * status.screenH);
    const clamp = (v, hi) => Math.max(0, Math.min(v, hi - 1));
    return { x: clamp(x, status.screenW), y: clamp(y, status.screenH) };
  };

  const clearInputErrorTimer = () => {
    if (inputErrorTimerRef.current) {
      clearTimeout(inputErrorTimerRef.current);
      inputErrorTimerRef.current = null;
    }
  };

  const send = async (body) => {
    try {
      await axios.post('/api/devices/astera/input', body);
      // A later successful input is the clearest signal the problem is
      // gone — clear immediately rather than waiting for the timer.
      clearInputErrorTimer();
      setInputError(null);
    } catch (err) {
      clearInputErrorTimer();
      setInputError(err?.response?.data?.detail || 'input refused');
      inputErrorTimerRef.current = setTimeout(() => setInputError(null), INPUT_ERROR_MS);
    }
  };

  // A drag that leaves the image before release is a normal gesture (a
  // swipe toward the mirrored screen's edge, dragging a colour wheel past
  // its border, etc). The native pointerup then fires on whatever element
  // is under the cursor, not the <img> — so pointerdown captures the
  // pointer, and cleanup listens on window for pointerup/pointercancel
  // regardless of where they land. setPointerCapture itself is also
  // attempted for browsers that honor it, but jsdom does not implement it
  // (hence the guarded call), so the window-level listeners are what
  // actually keep the gesture alive under test and in any environment
  // without capture support.
  const gestureCleanupRef = useRef(null);

  const endGesture = () => {
    if (gestureCleanupRef.current) {
      gestureCleanupRef.current();
      gestureCleanupRef.current = null;
    }
  };

  useEffect(() => () => endGesture(), []);

  const finishGesture = (e) => {
    const down = downRef.current;
    downRef.current = null;
    const up = toDevice(e);
    if (!down || !down.pt || !up) return;
    const moved = Math.hypot(e.clientX - down.clientX, e.clientY - down.clientY);
    if (moved < TAP_SLOP_PX) {
      send({ action: 'tap', x: up.x, y: up.y });
    } else {
      send({ action: 'swipe', x: down.pt.x, y: down.pt.y, x2: up.x, y2: up.y,
             durationMs: Math.max(50, Math.min(Date.now() - down.at, 5000)) });
    }
  };

  const releaseCapture = (pointerId) => {
    const el = imgRef.current;
    if (el && typeof el.releasePointerCapture === 'function') {
      try { el.releasePointerCapture(pointerId); } catch { /* not captured, or unsupported */ }
    }
  };

  const onPointerDown = (e) => {
    // Clear any stale, never-finished gesture before starting a new one.
    endGesture();
    downRef.current = { pt: toDevice(e), clientX: e.clientX, clientY: e.clientY,
                        at: Date.now() };

    const el = e.currentTarget;
    if (typeof el.setPointerCapture === 'function') {
      try { el.setPointerCapture(e.pointerId); } catch { /* unsupported, e.g. jsdom */ }
    }

    const handleUp = (ev) => {
      endGesture();
      releaseCapture(ev.pointerId);
      finishGesture(ev);
    };
    const handleCancel = (ev) => {
      endGesture();
      releaseCapture(ev.pointerId);
      // An interrupted gesture (e.g. the OS took over the touch) must not
      // be mistaken for the start of the next one.
      downRef.current = null;
    };
    window.addEventListener('pointerup', handleUp);
    window.addEventListener('pointercancel', handleCancel);
    gestureCleanupRef.current = () => {
      window.removeEventListener('pointerup', handleUp);
      window.removeEventListener('pointercancel', handleCancel);
    };
  };

  if (!status) {
    return <div className="text-[10px] font-mono text-text-muted py-6 px-2">connecting…</div>;
  }

  if (!status.available) {
    return (
      <div className="text-[10px] font-mono text-text-muted py-6 px-2 space-y-2">
        <div>{status.reason || 'tablet unavailable'}</div>
        {!status.disabled && (
          <button onClick={reconnect}
            className="px-2 py-1 border border-[var(--color-border)] rounded-sm hover:border-brand">
            Reconnect
          </button>
        )}
      </div>
    );
  }

  const age = status.lastFrameAgeSec;
  const stale = typeof age === 'number' && age > STALE_AFTER_SEC;

  return (
    <div className="px-2 py-3 space-y-2">
      <div className="text-[10px] font-mono text-text-muted flex gap-3 flex-wrap items-center">
        <span>{status.deviceModel || 'tablet'}</span>
        <span>Android {status.androidVersion || '?'}</span>
        <span>{status.screenW} × {status.screenH}</span>
        {stale && (
          <span className="text-warn">stale — last frame {age}s ago</span>
        )}
      </div>

      <div className="text-[9px] font-mono text-text-muted">
        still frames at about 2 fps · live video and smooth dragging coming soon
      </div>

      {frameError && (
        <div className="text-[10px] font-mono text-text-muted">{frameError}</div>
      )}

      {inputError && (
        <div className="text-[10px] font-mono text-warn">input: {inputError}</div>
      )}

      {frameUrl && (
        <img ref={imgRef} src={frameUrl} alt="tablet screen"
             onPointerDown={onPointerDown}
             draggable={false}
             className={'border border-[var(--color-border)] max-h-[70vh] w-auto touch-none select-none cursor-pointer ' +
                        (stale ? 'opacity-60' : '')} />
      )}

      <div className="flex gap-2">
        {[['Back', 'BACK'], ['Home', 'HOME'], ['Recents', 'APP_SWITCH']].map(([label, keycode]) => (
          <button key={keycode}
            onClick={() => send({ action: 'key', keycode })}
            className="text-[10px] font-mono px-2 py-1 border border-[var(--color-border)] rounded-sm hover:border-brand">
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
