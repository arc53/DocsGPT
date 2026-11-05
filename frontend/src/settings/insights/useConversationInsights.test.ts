import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const store = vi.hoisted(() => ({ preference: { token: 't' } }));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(store),
}));
const getConversationInsights = vi.hoisted(() => vi.fn());
vi.mock('../../api/services/userService', () => ({
  default: { getConversationInsights },
}));

import type { ConversationInsights } from '../types';
import {
  INSIGHTS_REFRESH_MS,
  useConversationInsights,
} from './useConversationInsights';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

/** A response whose window has `labelled` of `turns` answers labelled. */
const body = (labelled: number, unlabelled: number) =>
  ({
    success: true,
    available: true,
    enabled: true,
    coverage: {
      turns: labelled + unlabelled,
      labelled_turns: labelled,
      unlabelled_recent_turns: unlabelled,
    },
  }) as unknown as ConversationInsights;

const respond = (payload: unknown, ok = true) =>
  Promise.resolve({ ok, json: () => Promise.resolve(payload) });

// The sweep labels a window's answers every few minutes: while it is still
// at it the page asks again on its own, quietly, so the progress bar and
// the partial figures move without a reload.
describe('useConversationInsights refresh while labelling', () => {
  let container: HTMLDivElement;
  let root: Root;
  let seen: ReturnType<typeof useConversationInsights>;
  const statuses: string[] = [];
  let hidden = false;

  function Probe() {
    seen = useConversationInsights('agent-1', 'last_30_days');
    statuses.push(seen.status);
    return null;
  }

  const flush = () => act(async () => undefined);
  const tick = (ms = INSIGHTS_REFRESH_MS) =>
    act(async () => {
      vi.advanceTimersByTime(ms);
    });

  beforeEach(() => {
    vi.useFakeTimers();
    getConversationInsights.mockReset();
    statuses.length = 0;
    hidden = false;
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => hidden,
    });
    container = document.createElement('div');
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    vi.useRealTimers();
    Reflect.deleteProperty(document, 'hidden');
  });

  const mount = async () => {
    act(() => root.render(createElement(Probe)));
    await flush();
  };

  it('asks again each period while analyzing, without going back to loading', async () => {
    getConversationInsights
      .mockReturnValueOnce(respond(body(2, 40)))
      .mockReturnValueOnce(respond(body(8, 34)));
    await mount();
    expect(seen.data?.coverage.labelled_turns).toBe(2);
    statuses.length = 0;

    await tick(INSIGHTS_REFRESH_MS - 1);
    expect(getConversationInsights).toHaveBeenCalledTimes(1);
    await tick(1);
    expect(getConversationInsights).toHaveBeenCalledTimes(2);
    expect(seen.status).toBe('ready');
    expect(seen.data?.coverage.labelled_turns).toBe(8);
    expect(statuses).not.toContain('loading');
  });

  it('keeps asking while partial, and stops once the window is labelled', async () => {
    getConversationInsights
      .mockReturnValueOnce(respond(body(30, 5)))
      .mockReturnValueOnce(respond(body(35, 0)));
    await mount();
    await tick();
    expect(getConversationInsights).toHaveBeenCalledTimes(2);
    expect(seen.data?.coverage.unlabelled_recent_turns).toBe(0);
    await tick();
    await tick();
    expect(getConversationInsights).toHaveBeenCalledTimes(2);
  });

  it('never polls a window that is already labelled', async () => {
    getConversationInsights.mockReturnValue(respond(body(30, 0)));
    await mount();
    await tick();
    expect(getConversationInsights).toHaveBeenCalledTimes(1);
  });

  it('keeps the figures when a background refresh fails', async () => {
    getConversationInsights
      .mockReturnValueOnce(respond(body(2, 40)))
      .mockReturnValueOnce(respond({}, false))
      .mockReturnValueOnce(respond({ success: false }))
      .mockReturnValueOnce(respond(body(9, 33)));
    await mount();
    await tick();
    expect(seen.status).toBe('ready');
    expect(seen.data?.coverage.labelled_turns).toBe(2);
    await tick();
    expect(seen.status).toBe('ready');
    expect(seen.data?.coverage.labelled_turns).toBe(2);
    // A failure doesn't stop the polling: the next period tries again.
    await tick();
    expect(seen.data?.coverage.labelled_turns).toBe(9);
  });

  it('pauses while the tab is hidden and asks again on return', async () => {
    getConversationInsights
      .mockReturnValueOnce(respond(body(2, 40)))
      .mockReturnValueOnce(respond(body(12, 30)));
    await mount();
    hidden = true;
    await tick();
    await tick();
    expect(getConversationInsights).toHaveBeenCalledTimes(1);

    hidden = false;
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(getConversationInsights).toHaveBeenCalledTimes(2);
    expect(seen.data?.coverage.labelled_turns).toBe(12);
  });

  it('drops a background answer that lands after a newer request', async () => {
    let resolveStale: (value: unknown) => void = () => undefined;
    getConversationInsights
      .mockReturnValueOnce(respond(body(2, 40)))
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveStale = resolve;
        }),
      )
      .mockReturnValueOnce(respond(body(20, 22)));
    await mount();
    await tick();
    // Retry asks again in the foreground while the poll is in flight.
    await act(async () => seen.retry());
    expect(seen.data?.coverage.labelled_turns).toBe(20);
    await act(async () => {
      resolveStale({ ok: true, json: () => Promise.resolve(body(5, 37)) });
    });
    expect(seen.data?.coverage.labelled_turns).toBe(20);
  });
});
