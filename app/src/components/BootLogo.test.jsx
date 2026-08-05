import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, afterEach } from 'vitest';
import Header from './Header';
import Home from '../pages/Home';
import { BootProvider, phaseAt } from './BootLogo';

const realMatchMedia = window.matchMedia;

function setReducedMotion(matches) {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: String(query).includes('prefers-reduced-motion') ? matches : false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

afterEach(() => {
  window.matchMedia = realMatchMedia;
  vi.restoreAllMocks();
});

describe('boot phase outside a provider', () => {
  // Every route except Home renders Header with no BootProvider above it. If
  // the fallback in useBoot() regresses, the lockup and nav go dim app-wide
  // and nothing else fails — there is no error, just a permanently half-lit
  // header. This is the test that would catch it.
  it('renders the header fully lit with no BootProvider', () => {
    render(<MemoryRouter><Header /></MemoryRouter>);

    const mark = screen.getByLabelText('Five12 Logic');
    expect(parseFloat(mark.style.opacity)).toBeCloseTo(1, 5);
    // Header builds this string as (0.45 * lit).toFixed(3); lit === 1 settled.
    expect(mark.style.filter).toContain('0.450');

    const navHome = screen.getByRole('link', { name: 'Home' });
    expect(parseFloat(navHome.style.opacity)).toBeCloseTo(1, 5);
  });

  // Guards the assertions above against going vacuous: they only mean
  // something if an unsettled phase is actually dimmer than a settled one.
  it('is dim at the start of a boot, so "fully lit" is a real distinction', () => {
    expect(phaseAt(0).headerLit).toBeLessThan(0.2);
    expect(phaseAt(0).navLit).toBeLessThan(0.2);
  });
});

describe('prefers-reduced-motion', () => {
  it('lands on the settled frame immediately and schedules no animation', () => {
    setReducedMotion(true);
    const raf = vi.spyOn(window, 'requestAnimationFrame');

    render(<BootProvider><Home /></BootProvider>);

    // start() must return before scheduling a frame, not animate invisibly.
    expect(raf).not.toHaveBeenCalled();

    const heading = screen.getByRole('heading', { name: /ready/i });
    expect(parseFloat(heading.style.opacity)).toBeCloseTo(1, 5);
  });

  // Without this, the test above would still pass if the boot never ran at
  // all — which would be a different bug wearing the same green tick.
  it('does animate when reduced motion is not requested', () => {
    setReducedMotion(false);
    const raf = vi.spyOn(window, 'requestAnimationFrame');

    render(<BootProvider><Home /></BootProvider>);

    expect(raf).toHaveBeenCalled();
  });
});
