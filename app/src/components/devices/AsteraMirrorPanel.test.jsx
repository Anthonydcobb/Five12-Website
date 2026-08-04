import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import axios from 'axios';
import AsteraMirrorPanel from './AsteraMirrorPanel';

vi.mock('axios');

function statusOf(overrides) {
  return { data: { available: true, disabled: false, alerts: [], deviceModel: 'SM-X200',
                   androidVersion: '14', screenW: 1080, screenH: 2400,
                   mirrorRunning: true, lastFrameAgeSec: 0.2, ...overrides } };
}

// vi.advanceTimersByTimeAsync(bigMs) in one shot does not reliably cascade
// through a chain of promise -> state update -> newly-scheduled setTimeout
// more than one level deep (the React scheduler and the mocked clock both
// need a turn). Stepping in small increments lets every level catch up.
async function advanceStepped(totalMs, step = 50) {
  for (let t = 0; t < totalMs; t += step) {
    await vi.advanceTimersByTimeAsync(step);
  }
}

beforeEach(() => {
  global.URL.createObjectURL = vi.fn(() => 'blob:fake');
  global.URL.revokeObjectURL = vi.fn();
  axios.post.mockResolvedValue({ data: { ok: true, detail: '' } });
});

afterEach(() => { vi.clearAllMocks(); });

describe('AsteraMirrorPanel', () => {
  it('names the env var when the gate is off', async () => {
    axios.get.mockResolvedValue(statusOf({ available: false, disabled: true,
                                           reason: 'tablet mirror disabled — set FIVE12_MIRROR_TOOLS=1 to enable' }));
    render(<AsteraMirrorPanel />);
    expect(await screen.findByText(/FIVE12_MIRROR_TOOLS/)).toBeInTheDocument();
  });

  it('distinguishes disabled from offline', async () => {
    axios.get.mockResolvedValue(statusOf({ available: false, disabled: false,
                                           reason: 'tablet offline' }));
    render(<AsteraMirrorPanel />);
    expect(await screen.findByText(/tablet offline/i)).toBeInTheDocument();
    expect(screen.queryByText(/FIVE12_MIRROR_TOOLS/)).not.toBeInTheDocument();
  });

  it('offers reconnect when offline and not when disabled', async () => {
    axios.get.mockResolvedValue(statusOf({ available: false, disabled: false,
                                           reason: 'tablet offline' }));
    const { unmount } = render(<AsteraMirrorPanel />);
    expect(await screen.findByRole('button', { name: /reconnect/i })).toBeInTheDocument();
    unmount();

    axios.get.mockResolvedValue(statusOf({ available: false, disabled: true,
                                           reason: 'disabled — set FIVE12_MIRROR_TOOLS=1' }));
    render(<AsteraMirrorPanel />);
    await screen.findByText(/FIVE12_MIRROR_TOOLS/);
    expect(screen.queryByRole('button', { name: /reconnect/i })).not.toBeInTheDocument();
  });

  it('shows the device facts when available', async () => {
    axios.get.mockResolvedValue(statusOf({}));
    render(<AsteraMirrorPanel />);
    expect(await screen.findByText(/SM-X200/)).toBeInTheDocument();
    expect(screen.getByText(/1080\s*×\s*2400/)).toBeInTheDocument();
  });

  it('states that live video is coming', async () => {
    axios.get.mockResolvedValue(statusOf({}));
    render(<AsteraMirrorPanel />);
    expect(await screen.findByText(/coming soon/i)).toBeInTheDocument();
  });

  it('marks a stale frame with its age', async () => {
    axios.get.mockResolvedValue(statusOf({ lastFrameAgeSec: 12.4 }));
    render(<AsteraMirrorPanel />);
    await waitFor(() => expect(screen.getByText(/stale/i)).toBeInTheDocument());
    expect(screen.getByText(/12\.4s/)).toBeInTheDocument();
  });

  it('does not mark a fresh frame stale', async () => {
    axios.get.mockResolvedValue(statusOf({ lastFrameAgeSec: 0.3 }));
    render(<AsteraMirrorPanel />);
    await screen.findByText(/SM-X200/);
    expect(screen.queryByText(/stale/i)).not.toBeInTheDocument();
  });

  // Measured on the real tablet (SM-T290): screencap round-trip is 514-644 ms,
  // mean 529. A fixed interval shorter than that stacks requests forever. The
  // next capture must be scheduled from the completion of the last one, not
  // from a timer that keeps firing regardless.
  it('never runs two captures at once when a capture outlives the interval', async () => {
    vi.useFakeTimers();
    let inFlight = 0;
    let maxInFlight = 0;
    let frameCalls = 0;
    axios.get.mockImplementation((url) => {
      if (String(url).includes('/frame')) {
        frameCalls += 1;
        inFlight += 1;
        maxInFlight = Math.max(maxInFlight, inFlight);
        return new Promise((resolve) => {
          setTimeout(() => {
            inFlight -= 1;
            resolve({ data: new Blob(['x']) });
          }, 1200);
        });
      }
      return Promise.resolve(statusOf({}));
    });

    render(<AsteraMirrorPanel />);
    // Let the status request settle so the frame effect actually mounts and
    // registers its schedule. Without this the advance below drains its queue
    // before the effect exists, and the assertions pass vacuously.
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(6000);

    // Sanity: the panel must really be polling, or the concurrency
    // assertion proves nothing.
    expect(frameCalls).toBeGreaterThan(1);
    expect(maxInFlight).toBe(1);
    vi.useRealTimers();
  });

  // --- object-URL lifecycle -------------------------------------------
  // These give /status and /frame independent responses (a blanket
  // mockResolvedValue would make /frame resolve with status-shaped data,
  // which hides everything below).

  it('renders the frame image with the created object URL', async () => {
    axios.get.mockImplementation((url) => {
      if (String(url).includes('/frame')) {
        return Promise.resolve({ data: new Blob(['frame-bytes'], { type: 'image/png' }) });
      }
      return Promise.resolve(statusOf({}));
    });

    render(<AsteraMirrorPanel />);

    const img = await screen.findByAltText('tablet screen');
    expect(img).toHaveAttribute('src', 'blob:fake');
    expect(URL.createObjectURL).toHaveBeenCalled();
  });

  it('revokes every superseded frame URL as new frames arrive', async () => {
    // Distinct URLs per creation so "superseded" is actually observable —
    // with the beforeEach's constant 'blob:fake' stub, deleting every
    // revoke call would still leave the test unable to tell.
    let n = 0;
    URL.createObjectURL = vi.fn(() => `blob:${n++}`);

    vi.useFakeTimers();
    axios.get.mockImplementation((url) => {
      if (String(url).includes('/frame')) {
        return Promise.resolve({ data: new Blob(['x']) });
      }
      return Promise.resolve(statusOf({}));
    });

    render(<AsteraMirrorPanel />);
    await advanceStepped(3000);
    vi.useRealTimers();

    const created = URL.createObjectURL.mock.calls.length;
    const revoked = URL.revokeObjectURL.mock.calls.length;
    expect(created).toBeGreaterThan(2);
    // Every creation but the one currently on screen must have been
    // revoked. Deleting the revoke call collapses this to 0 and fails.
    expect(revoked).toBe(created - 1);
  });

  it('revokes the outstanding frame URL on unmount', async () => {
    axios.get.mockImplementation((url) => {
      if (String(url).includes('/frame')) {
        return Promise.resolve({ data: new Blob(['x']) });
      }
      return Promise.resolve(statusOf({}));
    });

    const { unmount } = render(<AsteraMirrorPanel />);
    await screen.findByAltText('tablet screen');
    const lastUrl = URL.createObjectURL.mock.results.at(-1).value;

    unmount();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith(lastUrl);
  });

  // --- Finding 1: the real backend reason must survive a Blob error body ---
  it('surfaces the backend reason when the frame request fails with a Blob error body', async () => {
    const reasonBlob = new Blob([JSON.stringify({ reason: 'capture already in progress' })],
                                { type: 'application/json' });
    axios.get.mockImplementation((url) => {
      if (String(url).includes('/frame')) {
        const err = new Error('Request failed with status code 503');
        err.response = { status: 503, data: reasonBlob };
        return Promise.reject(err);
      }
      return Promise.resolve(statusOf({}));
    });

    render(<AsteraMirrorPanel />);

    expect(await screen.findByText(/capture already in progress/)).toBeInTheDocument();
  });

  it('falls back to the generic message when the Blob error body is unparseable', async () => {
    const badBlob = new Blob(['not json'], { type: 'application/json' });
    axios.get.mockImplementation((url) => {
      if (String(url).includes('/frame')) {
        const err = new Error('Request failed with status code 503');
        err.response = { status: 503, data: badBlob };
        return Promise.reject(err);
      }
      return Promise.resolve(statusOf({}));
    });

    render(<AsteraMirrorPanel />);

    expect(await screen.findByText(/frame unavailable/)).toBeInTheDocument();
  });

  // --- Finding 2: an out-of-order resolution must not clobber a newer frame ---
  // Real timers throughout: driving this through STATUS_MS-spaced live
  // transitions with vi.advanceTimersByTimeAsync proved unreliable here —
  // a single large advance does not reliably cascade through more than one
  // level of promise -> state update -> newly-scheduled timer, and the
  // deterministic part of this test (which of two responses wins) comes
  // from the explicit promise resolvers below, not from timing.
  //
  // Reproduces the race the only way this component's public behaviour
  // allows: a live -> offline -> live flip tears down the frame-polling
  // effect while its request is still in flight, then starts a fresh one.
  // NOTE: with the current "chain from completion" scheduling (see
  // FRAME_MS above), a single effect instance can never have two frame
  // requests in flight at once, so this cross-instance path is the only
  // reachable trigger — and it is *also* fully covered by the pre-existing
  // per-instance `alive` flag on its own. Verified by temporarily reverting
  // only the `generation !== generationRef.current` check (leaving `alive`
  // intact): this test still passed. So this test guards the required
  // observable behaviour (a stale frame must never replace a newer one),
  // but does not, by itself, prove the generation token is load-bearing in
  // the current codebase — see the fix-pass report for detail.
  it('does not let a stale frame response replace a newer one that already resolved', async () => {
    let n = 0;
    URL.createObjectURL = vi.fn(() => `blob:${n++}`);

    let frameCalls = 0;
    const frameResolvers = [];
    let statusCalls = 0;
    axios.get.mockImplementation((url) => {
      if (String(url).includes('/frame')) {
        frameCalls += 1;
        return new Promise((resolve) => { frameResolvers.push(resolve); });
      }
      statusCalls += 1;
      // available -> briefly offline (tears down the in-flight frame poll,
      // leaving its promise still unsettled) -> available again (starts a
      // second, independent frame poll). The first poll's promise is then
      // resolved last, out of order, once the second is already on screen.
      if (statusCalls === 2) {
        return Promise.resolve(statusOf({ available: false, disabled: false,
                                          reason: 'tablet offline' }));
      }
      return Promise.resolve(statusOf({}));
    });

    render(<AsteraMirrorPanel />);
    await waitFor(() => expect(frameCalls).toBe(1));

    // Two more real STATUS_MS (3000ms) ticks: offline, then online again.
    await waitFor(() => expect(statusCalls).toBeGreaterThanOrEqual(2), { timeout: 4000 });
    await waitFor(() => expect(statusCalls).toBeGreaterThanOrEqual(3), { timeout: 4000 });
    await waitFor(() => expect(frameCalls).toBe(2));

    // Resolve the newer (second) request first.
    frameResolvers[1]({ data: new Blob(['second']) });
    const img = await screen.findByAltText('tablet screen');
    const newerUrl = img.getAttribute('src');
    expect(newerUrl).toBeTruthy();

    // The stale first request resolves late, after the newer frame is
    // already displayed.
    frameResolvers[0]({ data: new Blob(['first']) });
    await new Promise((resolve) => setTimeout(resolve, 100));

    expect(screen.getByAltText('tablet screen')).toHaveAttribute('src', newerUrl);
  }, 15000);

  // --- tap, swipe and navigation control -------------------------------
  // jsdom does not implement the PointerEvent constructor, so these use
  // Testing Library's fireEvent.pointerDown/pointerUp (which synthesizes a
  // real pointer event) rather than `new PointerEvent(...)`.

  function mockImageBox(el, box) {
    vi.spyOn(el, 'getBoundingClientRect').mockReturnValue({
      left: box.left, top: box.top, width: box.width, height: box.height,
      right: box.left + box.width, bottom: box.top + box.height, x: box.left, y: box.top,
    });
  }

  it('converts a click to device pixels at a non-1:1 display scale', async () => {
    axios.get.mockResolvedValue(statusOf({}));
    render(<AsteraMirrorPanel />);
    const img = await screen.findByAltText('tablet screen');
    // displayed at 270x600 for a 1080x2400 device — exactly quarter scale
    mockImageBox(img, { left: 10, top: 20, width: 270, height: 600 });

    fireEvent.pointerDown(img, { clientX: 10 + 135, clientY: 20 + 300 });
    fireEvent.pointerUp(img, { clientX: 10 + 135, clientY: 20 + 300 });

    await waitFor(() => expect(axios.post).toHaveBeenCalled());
    expect(axios.post).toHaveBeenCalledWith('/api/devices/astera/input',
      { action: 'tap', x: 540, y: 1200 });
  });

  it('sends a swipe when the pointer moves far enough', async () => {
    axios.get.mockResolvedValue(statusOf({}));
    render(<AsteraMirrorPanel />);
    const img = await screen.findByAltText('tablet screen');
    mockImageBox(img, { left: 0, top: 0, width: 270, height: 600 });

    fireEvent.pointerDown(img, { clientX: 10, clientY: 10 });
    fireEvent.pointerUp(img, { clientX: 100, clientY: 200 });

    await waitFor(() => expect(axios.post).toHaveBeenCalled());
    const [, body] = axios.post.mock.calls[0];
    expect(body.action).toBe('swipe');
    expect(body).toMatchObject({ x: 40, y: 40, x2: 400, y2: 800 });
    expect(typeof body.durationMs).toBe('number');
  });

  it('sends allowed keycodes from the nav buttons', async () => {
    axios.get.mockResolvedValue(statusOf({}));
    render(<AsteraMirrorPanel />);
    (await screen.findByRole('button', { name: /back/i })).click();
    await waitFor(() => expect(axios.post).toHaveBeenCalledWith(
      '/api/devices/astera/input', { action: 'key', keycode: 'BACK' }));
  });

  it('has no controls at all when the tablet is offline', async () => {
    axios.get.mockResolvedValue(statusOf({ available: false, disabled: false,
                                           reason: 'tablet offline' }));
    render(<AsteraMirrorPanel />);
    await screen.findByText(/tablet offline/i);
    expect(screen.queryByRole('button', { name: /back/i })).not.toBeInTheDocument();
    expect(screen.queryByAltText('tablet screen')).not.toBeInTheDocument();
  });

  // --- fix pass: pointer capture keeps a drag alive past the image edge ---
  // Without setPointerCapture (and the window-level pointerup/pointercancel
  // fallback jsdom needs, since it doesn't implement real capture), the
  // native pointerup would fire on whatever element is under the cursor —
  // not the <img> — and this gesture would be silently dropped: no request
  // sent, downRef left set. We prove it by releasing on `window` itself,
  // which is never an ancestor of the <img> in the delegated-event sense,
  // so this can only pass if something outside the <img>'s own handlers is
  // catching the release.
  it('still sends the swipe when the pointer is released outside the image', async () => {
    axios.get.mockResolvedValue(statusOf({}));
    render(<AsteraMirrorPanel />);
    const img = await screen.findByAltText('tablet screen');
    mockImageBox(img, { left: 0, top: 0, width: 270, height: 600 });

    fireEvent.pointerDown(img, { clientX: 50, clientY: 50 });
    // The drag crosses the image's right edge (e.g. a swipe toward the
    // mirrored screen's border, or dragging a colour wheel past its rim)
    // and the pointerup lands somewhere that is not the <img> at all.
    fireEvent.pointerUp(window, { clientX: 320, clientY: 50 });

    await waitFor(() => expect(axios.post).toHaveBeenCalled());
    const [, body] = axios.post.mock.calls[0];
    // down: (50,50) in a 270x600 box over a 1080x2400 device -> (200,200).
    // up: (320,50) -> x ratio 320/270*1080 = 1280, clamped to 1079; y=200.
    expect(body).toMatchObject({ action: 'swipe', x: 200, y: 200, x2: 1079, y2: 200 });
  });

  it('clears the pending gesture on pointercancel so it cannot leak into the next one', async () => {
    axios.get.mockResolvedValue(statusOf({}));
    render(<AsteraMirrorPanel />);
    const img = await screen.findByAltText('tablet screen');
    mockImageBox(img, { left: 0, top: 0, width: 270, height: 600 });

    fireEvent.pointerDown(img, { clientX: 50, clientY: 50 });
    fireEvent.pointerCancel(img, {});
    // A pointerup that arrives after the cancel must not be treated as the
    // release of the cancelled gesture, even though it lands right back on
    // the image (dispatched here on the <img> itself, deliberately, so this
    // still catches the old img-only onPointerUp handler if it ever comes
    // back).
    fireEvent.pointerUp(img, { clientX: 50, clientY: 50 });

    // Give any (incorrect) queued send() a chance to fire.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(axios.post).not.toHaveBeenCalled();
  });

  // --- fix pass: an input error must outlive the next frame poll -------
  // The frame-poll effect calls setFrameError(null) on every successful
  // tick (~750ms, FRAME_MS). Before this fix, send() reported failures
  // through that same frameError state, so a rejected tap/swipe/key would
  // be wiped from the screen well under a second after it appeared.
  it('keeps an input error visible across a subsequent successful frame poll', async () => {
    axios.get.mockImplementation((url) => {
      if (String(url).includes('/frame')) {
        return Promise.resolve({ data: new Blob(['x']) });
      }
      return Promise.resolve(statusOf({}));
    });
    axios.post.mockRejectedValueOnce({ response: { data: { detail: 'x out of bounds' } } });

    render(<AsteraMirrorPanel />);
    const img = await screen.findByAltText('tablet screen');
    mockImageBox(img, { left: 0, top: 0, width: 270, height: 600 });

    fireEvent.pointerDown(img, { clientX: 135, clientY: 300 });
    fireEvent.pointerUp(img, { clientX: 135, clientY: 300 });

    expect(await screen.findByText(/x out of bounds/)).toBeInTheDocument();

    // Real time, past FRAME_MS (750ms), so at least one more successful
    // frame poll completes and calls setFrameError(null) after the input
    // error was set.
    await new Promise((resolve) => setTimeout(resolve, 1100));

    expect(screen.getByText(/x out of bounds/)).toBeInTheDocument();
  }, 10000);

  // --- fix pass: coordinate rounding must be exercised by a scale that
  // doesn't divide evenly, or a regression that drops Math.round would
  // pass every existing test while sending floats the backend rejects. ---
  it('rounds coordinates to integers at a non-dividing display scale', async () => {
    axios.get.mockResolvedValue(statusOf({}));
    render(<AsteraMirrorPanel />);
    const img = await screen.findByAltText('tablet screen');
    // 273x601 against a 1080x2400 device does not divide evenly in either
    // axis, unlike the quarter-scale boxes used elsewhere in this file.
    mockImageBox(img, { left: 5, top: 7, width: 273, height: 601 });

    fireEvent.pointerDown(img, { clientX: 5 + 100, clientY: 7 + 250 });
    fireEvent.pointerUp(img, { clientX: 5 + 100, clientY: 7 + 250 });

    await waitFor(() => expect(axios.post).toHaveBeenCalled());
    const [, body] = axios.post.mock.calls[0];
    expect(body.action).toBe('tap');
    // x: round(100/273*1080) = round(395.604...) = 396
    // y: round(250/601*2400) = round(998.336...) = 998
    expect(Number.isInteger(body.x)).toBe(true);
    expect(Number.isInteger(body.y)).toBe(true);
    expect(body).toMatchObject({ x: 396, y: 998 });
  });
});
