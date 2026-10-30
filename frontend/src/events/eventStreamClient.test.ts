import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  connectEventStream,
  type EventStreamHealth,
} from './eventStreamClient';

/** A stream body the test feeds by hand; aborting the request errors it. */
function openBody(signal: AbortSignal) {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  signal.addEventListener('abort', () => {
    try {
      controller.error(new DOMException('Aborted', 'AbortError'));
    } catch {
      // Already closed.
    }
  });
  const encoder = new TextEncoder();
  return {
    body,
    send: (text: string) => controller.enqueue(encoder.encode(text)),
  };
}

type Opened = ReturnType<typeof openBody>;

describe('connectEventStream', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let opened: Opened[];
  let health: EventStreamHealth[];

  /** Every request opens a stream that stays open until aborted. */
  const answerWithStreams = () =>
    fetchMock.mockImplementation((_url: string, init: RequestInit) => {
      const stream = openBody(init.signal as AbortSignal);
      opened.push(stream);
      return Promise.resolve(new Response(stream.body, { status: 200 }));
    });

  const connect = (
    extra: Partial<Parameters<typeof connectEventStream>[0]> = {},
  ) =>
    connectEventStream({
      token: 'tok',
      getLastEventId: () => null,
      onEvent: () => undefined,
      onHealthChange: (h) => health.push(h),
      ...extra,
    });

  beforeEach(() => {
    vi.useFakeTimers();
    opened = [];
    health = [];
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('keeps retrying after the error budget is spent, slowly', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const onErrorBudgetSpent = vi.fn();
    const conn = connect({ onErrorBudgetSpent });

    // The fast schedule tops out at 30 s; twenty failures fit in 15 minutes.
    await vi.advanceTimersByTimeAsync(15 * 60_000);
    expect(onErrorBudgetSpent).toHaveBeenCalledTimes(1);
    const afterBudget = fetchMock.mock.calls.length;
    expect(afterBudget).toBeGreaterThanOrEqual(20);

    // Still trying, about once a minute.
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    const slowRetries = fetchMock.mock.calls.length - afterBudget;
    expect(slowRetries).toBeGreaterThanOrEqual(4);
    expect(slowRetries).toBeLessThanOrEqual(6);
    expect(onErrorBudgetSpent).toHaveBeenCalledTimes(1);

    conn.close();
  });

  it('retries at once when the browser comes back online', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const conn = connect();
    await vi.advanceTimersByTimeAsync(15 * 60_000);
    const before = fetchMock.mock.calls.length;

    answerWithStreams();
    window.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock.mock.calls.length).toBe(before + 1);

    conn.close();
  });

  it('retries at once when the tab becomes visible', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const conn = connect();
    await vi.advanceTimersByTimeAsync(15 * 60_000);
    const before = fetchMock.mock.calls.length;

    answerWithStreams();
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock.mock.calls.length).toBe(before + 1);

    conn.close();
  });

  it('reconnects a stream that went silent, and stays on one that keeps alive', async () => {
    answerWithStreams();
    const conn = connect();
    await vi.advanceTimersByTimeAsync(3_000);
    expect(health).toEqual(['connecting', 'healthy']);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Keepalives every 15 s keep it open.
    for (let i = 0; i < 8; i++) {
      opened[0].send(': keepalive\n\n');
      await vi.advanceTimersByTimeAsync(15_000);
    }
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Nothing at all for a minute: a dead connection (a sleep, a dropped
    // network) the browser never reported. Drop it and connect again.
    await vi.advanceTimersByTimeAsync(61_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(health).toContain('unhealthy');

    conn.close();
  });

  it('drops a stale stream at once when the tab wakes', async () => {
    answerWithStreams();
    const conn = connect();
    await vi.advanceTimersByTimeAsync(3_000);
    // Silent for 40 s (under the idle limit), then the tab is shown again.
    await vi.advanceTimersByTimeAsync(40_000);
    window.dispatchEvent(new Event('focus'));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    conn.close();
  });

  it('leaves a live stream alone when the tab wakes', async () => {
    answerWithStreams();
    const conn = connect();
    await vi.advanceTimersByTimeAsync(3_000);
    opened[0].send(': keepalive\n\n');
    await vi.advanceTimersByTimeAsync(5_000);
    window.dispatchEvent(new Event('focus'));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    conn.close();
  });

  it('stops for good on close, wake events included', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const conn = connect();
    await vi.advanceTimersByTimeAsync(5_000);
    conn.close();
    const before = fetchMock.mock.calls.length;

    window.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(fetchMock.mock.calls.length).toBe(before);
  });

  it('still hands a run of 401s to the caller and stops', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 401 }));
    const onAuthFailure = vi.fn();
    connect({ onAuthFailure });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(onAuthFailure).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    window.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
