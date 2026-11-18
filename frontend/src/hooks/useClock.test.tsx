import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useClock } from './useClock';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('useClock', () => {
  let container: HTMLDivElement;
  let root: Root;
  let renders = 0;

  function Probe({ active, every }: { active?: boolean; every?: number }) {
    useClock(active, every);
    renders += 1;
    return null;
  }

  beforeEach(() => {
    vi.useFakeTimers();
    renders = 0;
    container = document.createElement('div');
    root = createRoot(container);
  });

  // One act per second: React folds updates inside one act into one render.
  const seconds = async (n: number) => {
    for (let i = 0; i < n; i += 1) {
      await act(async () => vi.advanceTimersByTime(1000));
    }
  };

  afterEach(() => {
    act(() => root.unmount());
    vi.useRealTimers();
  });

  it('ticks once a second by default', async () => {
    await act(async () => root.render(<Probe />));
    const before = renders;
    await seconds(3);
    expect(renders - before).toBe(3);
  });

  it('ticks at the pace it is given', async () => {
    // Nothing running on Now: the overdue marks only need minutes.
    await act(async () => root.render(<Probe every={30_000} />));
    const before = renders;
    await seconds(29);
    expect(renders).toBe(before);
    await seconds(1);
    expect(renders - before).toBe(1);
  });

  it('stands still while inactive', async () => {
    await act(async () => root.render(<Probe active={false} />));
    const before = renders;
    await seconds(5);
    expect(renders).toBe(before);
  });
});
