import { afterEach, describe, expect, it, vi } from 'vitest';

// Vitest runs in Node, which reports unhandled rejections on `process`; the
// app's tsconfig has no Node types, so reach it through globalThis.
type RejectionListener = (reason: unknown) => void;
const nodeProcess = (
  globalThis as unknown as {
    process: {
      on(event: 'unhandledRejection', listener: RejectionListener): void;
      off(event: 'unhandledRejection', listener: RejectionListener): void;
    };
  }
).process;

import { withThrottle } from './throttle';

describe('withThrottle GET dedupe', () => {
  const unhandled = vi.fn();

  afterEach(() => {
    nodeProcess.off('unhandledRejection', unhandled);
    unhandled.mockReset();
  });

  it('rejects the caller only, without an unhandled rejection', async () => {
    nodeProcess.on('unhandledRejection', unhandled);
    const fetchLike = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(new Response('ok'));
    const throttled = withThrottle(fetchLike);

    await expect(throttled('/api/models')).rejects.toThrow('Failed to fetch');
    // Give Node a turn to report anything left unhandled.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(unhandled).not.toHaveBeenCalled();

    // The failed request left the inflight map, so the next GET fetches anew.
    const response = await throttled('/api/models');
    expect(await response.text()).toBe('ok');
    expect(fetchLike).toHaveBeenCalledTimes(2);
  });

  it('shares one fetch between concurrent identical GETs', async () => {
    const fetchLike = vi.fn(async () => new Response('shared'));
    const throttled = withThrottle(fetchLike);

    const [a, b] = await Promise.all([
      throttled('/api/agents'),
      throttled('/api/agents'),
    ]);
    expect(await a.text()).toBe('shared');
    expect(await b.text()).toBe('shared');
    expect(fetchLike).toHaveBeenCalledTimes(1);
  });
});
