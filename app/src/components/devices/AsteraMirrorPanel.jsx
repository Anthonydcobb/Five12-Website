import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';

const STATUS_MS = 3000;
const FRAME_MS = 400;
const STALE_AFTER_SEC = 3;

export default function AsteraMirrorPanel() {
  const [status, setStatus] = useState(null);
  const [frameUrl, setFrameUrl] = useState(null);
  const [frameError, setFrameError] = useState(null);
  const urlRef = useRef(null);

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
    const grab = async () => {
      try {
        const resp = await axios.get('/api/devices/astera/frame',
                                     { responseType: 'blob' });
        if (!alive) return;
        const next = URL.createObjectURL(resp.data);
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = next;
        setFrameUrl(next);
        setFrameError(null);
      } catch (err) {
        if (alive) setFrameError(err?.response?.data?.reason || 'frame unavailable');
      }
    };
    grab();
    const i = setInterval(grab, FRAME_MS);
    return () => {
      alive = false;
      clearInterval(i);
      if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = null; }
    };
  }, [live]);

  const reconnect = async () => { await pollStatus(); };

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
        still frames at 2–3 fps · live video and smooth dragging coming soon
      </div>

      {frameError && (
        <div className="text-[10px] font-mono text-text-muted">{frameError}</div>
      )}

      {frameUrl && (
        <img src={frameUrl} alt="tablet screen"
             className={'border border-[var(--color-border)] max-h-[70vh] w-auto ' +
                        (stale ? 'opacity-60' : '')} />
      )}
    </div>
  );
}
