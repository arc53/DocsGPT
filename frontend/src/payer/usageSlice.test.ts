import { configureStore } from '@reduxjs/toolkit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/services/payerService', () => ({
  default: { getQuota: vi.fn() },
}));

import payerService, {
  type QuotaBucket,
  type QuotaResponse,
} from '../api/services/payerService';
import workspaceReducer, { switchWorkspace } from '../workspace/workspaceSlice';
import reducer, {
  chatUsageScope,
  connectUsage,
  createUsageListener,
  FOCUS_REFETCH_MS,
  loadUsage,
  STOPPED_FOCUS_REFETCH_MS,
  noteQuotaError,
  noteTurnFinished,
  noticeFor,
  selectQuota,
  selectUsageNotice,
  TURN_DEBOUNCE_MS,
  usageFocused,
} from './usageSlice';

const getQuota = vi.mocked(payerService.getQuota);

const RESET = '2026-12-01T00:00:00+00:00';

const bucket = (
  name: string,
  used: number,
  limit: number | null,
  budget: 'tokens' | 'cost' = 'cost',
): QuotaBucket => ({
  bucket: name,
  tokens:
    budget === 'tokens' ? { limit, used } : { limit: null, used: used * 1000 },
  cost: budget === 'cost' ? { limit, used } : { limit: null, used: 0 },
  resets_at: RESET,
});

const quota = (over: Partial<QuotaResponse> = {}): QuotaResponse => ({
  success: true,
  period: 'month',
  buckets: [bucket('all', 10, 100)],
  notice: null,
  parts: null,
  paused: null,
  ...over,
});

const makeStore = (token: string | null = 'tok') => {
  const listener = createUsageListener();
  const store = configureStore({
    reducer: {
      usage: reducer,
      workspace: workspaceReducer,
      preference: (state: { token: string | null } = { token }) => state,
    },
    middleware: (getDefault) => getDefault().concat(listener.middleware),
  });
  connectUsage(store);
  return { store, listener };
};

let current: ReturnType<typeof makeStore> | null = null;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-11-16T12:00:00Z'));
  getQuota.mockReset();
  getQuota.mockResolvedValue(quota());
});

afterEach(() => {
  current?.listener.clearListeners();
  current = null;
  connectUsage(null);
  vi.useRealTimers();
});

const start = async () => {
  current = makeStore();
  await current.store.dispatch(loadUsage());
  return current.store;
};

describe('usageSlice', () => {
  it('loads the quota with the token', async () => {
    const store = await start();
    expect(getQuota).toHaveBeenCalledWith('tok');
    expect(selectQuota(store.getState())?.buckets).toHaveLength(1);
  });

  it('refetches once, 30 s after the last of several finished turns', async () => {
    await start();
    getQuota.mockClear();
    noteTurnFinished();
    await vi.advanceTimersByTimeAsync(10_000);
    noteTurnFinished();
    await vi.advanceTimersByTimeAsync(TURN_DEBOUNCE_MS - 1);
    expect(getQuota).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(getQuota).toHaveBeenCalledTimes(1);
  });

  it('skips the after-turn refetch for an unlimited caller', async () => {
    getQuota.mockResolvedValue(quota({ buckets: [] }));
    await start();
    getQuota.mockClear();
    noteTurnFinished();
    await vi.advanceTimersByTimeAsync(TURN_DEBOUNCE_MS);
    expect(getQuota).not.toHaveBeenCalled();
  });

  it('refetches at once after a quota error', async () => {
    await start();
    getQuota.mockClear();
    noteQuotaError();
    await vi.advanceTimersByTimeAsync(0);
    expect(getQuota).toHaveBeenCalledTimes(1);
  });

  it('refetches on focus at most every 5 minutes', async () => {
    const store = await start();
    getQuota.mockClear();
    store.dispatch(usageFocused());
    await vi.advanceTimersByTimeAsync(0);
    expect(getQuota).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(FOCUS_REFETCH_MS);
    store.dispatch(usageFocused());
    await vi.advanceTimersByTimeAsync(0);
    expect(getQuota).toHaveBeenCalledTimes(1);
  });

  it('refetches on focus soon while stopped, so a raised limit opens the composer', async () => {
    getQuota.mockResolvedValueOnce(
      quota({ buckets: [bucket('all', 100, 100)] }),
    );
    getQuota.mockResolvedValue(quota({ buckets: [bucket('all', 100, 200)] }));
    const store = await start();
    expect(selectUsageNotice(store.getState(), 'direct')?.level).toBe(
      'reached',
    );
    expect(STOPPED_FOCUS_REFETCH_MS).toBeLessThan(FOCUS_REFETCH_MS);
    await vi.advanceTimersByTimeAsync(STOPPED_FOCUS_REFETCH_MS);
    store.dispatch(usageFocused());
    await vi.advanceTimersByTimeAsync(0);
    expect(getQuota).toHaveBeenCalledTimes(2);
    expect(selectUsageNotice(store.getState(), 'direct')).toBeNull();
  });

  it('refetches at the reset, so a stopped composer opens again', async () => {
    getQuota.mockResolvedValueOnce(
      quota({ buckets: [bucket('all', 100, 100)] }),
    );
    getQuota.mockResolvedValue(quota({ buckets: [bucket('all', 0, 100)] }));
    const store = await start();
    expect(selectUsageNotice(store.getState(), 'direct')?.level).toBe(
      'reached',
    );
    // Two weeks out: past one setTimeout's range is no reason to fire early.
    await vi.advanceTimersByTimeAsync(
      new Date(RESET).getTime() - Date.now() - 1000,
    );
    expect(getQuota).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(getQuota).toHaveBeenCalledTimes(2);
    expect(selectUsageNotice(store.getState(), 'direct')).toBeNull();
  });

  it('keeps the quota through a workspace switch: it is the person’s', async () => {
    const store = await start();
    getQuota.mockClear();
    store.dispatch(switchWorkspace('t1'));
    await vi.advanceTimersByTimeAsync(TURN_DEBOUNCE_MS);
    expect(getQuota).not.toHaveBeenCalled();
    expect(selectQuota(store.getState())?.buckets).toHaveLength(1);
  });

  it('drops an answer a newer load overtook', async () => {
    current = makeStore();
    let first: (value: QuotaResponse) => void = () => undefined;
    getQuota.mockImplementationOnce(
      () => new Promise((resolve) => (first = resolve)),
    );
    const older = current.store.dispatch(loadUsage());
    await current.store.dispatch(loadUsage({ force: true }));
    first(quota({ buckets: [] }));
    await older;
    expect(selectQuota(current.store.getState())?.buckets).toHaveLength(1);
  });

  it('keeps what it had when a load fails', async () => {
    const store = await start();
    getQuota.mockRejectedValueOnce(new Error('offline'));
    await store.dispatch(loadUsage({ force: true }));
    expect(selectQuota(store.getState())?.buckets).toHaveLength(1);
  });
});

describe('noticeFor', () => {
  it('is nothing under 80% and for an unlimited caller', () => {
    expect(noticeFor(quota(), 'direct')).toBeNull();
    expect(noticeFor(quota({ buckets: [] }), 'agent')).toBeNull();
    expect(noticeFor(null, 'agent')).toBeNull();
  });

  it('is near from 80% and reached at 100%', () => {
    const near = quota({ buckets: [bucket('all', 80, 100)] });
    expect(noticeFor(near, 'direct')).toEqual({
      level: 'near',
      percent: 80,
      bucket: 'all',
      budget: 'cost',
      resets_at: RESET,
    });
    const over = quota({ buckets: [bucket('all', 130, 100, 'tokens')] });
    expect(noticeFor(over, 'direct')).toMatchObject({
      level: 'reached',
      percent: 100,
      budget: 'tokens',
    });
  });

  it('counts only the buckets the chat spends from', () => {
    const agentSpent = quota({
      buckets: [bucket('all', 10, 100), bucket('agent', 100, 100)],
    });
    expect(noticeFor(agentSpent, 'direct')).toBeNull();
    expect(noticeFor(agentSpent, 'agent')?.level).toBe('reached');
  });

  it('without a scope is the server’s notice', () => {
    const notice = {
      level: 'near' as const,
      percent: 85,
      bucket: 'agent',
      budget: 'cost' as const,
      resets_at: RESET,
    };
    expect(noticeFor(quota({ notice }))).toBe(notice);
  });
});

describe('chatUsageScope', () => {
  it('is direct without an agent and agent with the person’s own', () => {
    expect(chatUsageScope(null)).toBe('direct');
    expect(chatUsageScope({})).toBe('agent');
    expect(
      chatUsageScope({
        access: 'owner',
        workspace: { kind: 'personal', team_id: null },
      }),
    ).toBe('agent');
  });

  it('is agent for a team’s agent or one shared with the person', () => {
    expect(
      chatUsageScope({
        access: 'viewer',
        workspace: { kind: 'team', team_id: 't1' },
        origin: 'team',
      }),
    ).toBe('agent');
    expect(
      chatUsageScope({
        access: 'viewer',
        workspace: { kind: 'personal', team_id: null },
        origin: 'shared',
      }),
    ).toBe('agent');
  });

  it('is agent for an agent reached by its link: a signed-in visitor pays for their own chat', () => {
    expect(
      chatUsageScope({
        access: 'viewer',
        allowed_actions: ['pin', 'use'],
        origin: 'link',
      }),
    ).toBe('agent');
  });
});
