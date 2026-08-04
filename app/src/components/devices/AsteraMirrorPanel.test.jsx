import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import axios from 'axios';
import AsteraMirrorPanel from './AsteraMirrorPanel';

vi.mock('axios');

function statusOf(overrides) {
  return { data: { available: true, disabled: false, alerts: [], deviceModel: 'SM-X200',
                   androidVersion: '14', screenW: 1080, screenH: 2400,
                   mirrorRunning: true, lastFrameAgeSec: 0.2, ...overrides } };
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
});
