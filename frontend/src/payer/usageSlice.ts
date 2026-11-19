import {
  createAction,
  createAsyncThunk,
  createListenerMiddleware,
  createSelector,
  createSlice,
} from '@reduxjs/toolkit';

import payerService, {
  type QuotaNotice,
  type QuotaPaused,
  type QuotaResponse,
} from '../api/services/payerService';

/** After a finished turn, the quota is read again this long after the last one. */
export const TURN_DEBOUNCE_MS = 30_000;
/** Coming back to the window reads the quota again at most this often. */
export const FOCUS_REFETCH_MS = 5 * 60_000;
/**
 * The same while an allowance is used up: someone may have raised the
 * limit, and the composer stays shut until a read says so.
 */
export const STOPPED_FOCUS_REFETCH_MS = 15_000;
/** Past the reset, so the server is already counting the new window. */
const RESET_SLACK_MS = 2_000;
/** One wait toward the reset; a month is past one setTimeout's range. */
const MAX_WAIT_MS = 24 * 60 * 60_000;
/** From this share of a budget the person is told they are near it. */
const NEAR_PERCENT = 80;

/**
 * Which allowance a chat spends from: `direct` without an agent, `agent`
 * with one. Both also spend from `all`.
 */
export type UsageScope = 'direct' | 'agent';

/**
 * Which of the person's allowances a chat spends from, as the server bills
 * it: `direct` without an agent, `agent` with any agent, their own, a
 * team's, one shared with them or one reached by its public link. In the app
 * the person is always signed in, and a signed-in person pays for their own
 * chat; an agent's publisher pays only for link visitors who aren't.
 *
 * Args:
 *   agent: The selected agent, or null for a chat without one.
 *
 * Returns:
 *   The scope.
 */
export function chatUsageScope(agent: unknown): UsageScope {
  return agent ? 'agent' : 'direct';
}

export type UsageState = {
  /** The last answer of `GET /api/user/quota`; null until one arrives. */
  quota: QuotaResponse | null;
  status: 'idle' | 'loading' | 'ready' | 'failed';
  /** When the quota was last read (ms). */
  loadedAt: number | null;
  /** The token it was read with; a different one reads again. */
  loadedFor: string | null;
  /** The newest load; an older one that answers late is dropped. */
  requestId: string | null;
};

type UsageRootState = {
  usage: UsageState;
  preference: { token: string | null };
};

const initialState: UsageState = {
  quota: null,
  status: 'idle',
  loadedAt: null,
  loadedFor: null,
  requestId: null,
};

/**
 * Reads the person's quota. Usage is the person's, not the workspace's, so a
 * workspace switch keeps it. `force` reads even while a load runs.
 */
export const loadUsage = createAsyncThunk<
  { quota: QuotaResponse; token: string | null },
  { force?: boolean } | undefined,
  { state: UsageRootState }
>(
  'usage/load',
  async (_arg, { getState }) => {
    const token = getState().preference.token;
    return { quota: await payerService.getQuota(token), token };
  },
  {
    condition: (arg, { getState }) =>
      !!arg?.force || getState().usage.status !== 'loading',
  },
);

/** A chat turn ended (answered or failed): its spend may move the meter. */
export const usageTurnFinished = createAction('usage/turnFinished');
/** A chat was stopped for the person's allowance. */
export const usageQuotaError = createAction('usage/quotaError');
/** The window got focus again. */
export const usageFocused = createAction('usage/focused');

const usageSlice = createSlice({
  name: 'usage',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(loadUsage.pending, (state, action) => {
        state.status = 'loading';
        state.requestId = action.meta.requestId;
      })
      .addCase(loadUsage.fulfilled, (state, action) => {
        if (action.meta.requestId !== state.requestId) return;
        state.quota = action.payload.quota;
        state.status = 'ready';
        state.loadedAt = Date.now();
        state.loadedFor = action.payload.token;
      })
      .addCase(loadUsage.rejected, (state, action) => {
        if (action.meta.requestId !== state.requestId) return;
        // What was shown stays: an outage must not hide a stop, nor invent one.
        state.status = 'failed';
      });
  },
});

export default usageSlice.reducer;

const isUnlimited = (state: UsageState): boolean =>
  state.status === 'ready' && (state.quota?.buckets.length ?? 0) === 0;

const nextReset = (quota: QuotaResponse | null): number | null => {
  const times = (quota?.buckets ?? [])
    .map((bucket) => new Date(bucket.resets_at).getTime())
    .filter((time) => Number.isFinite(time));
  return times.length ? Math.min(...times) : null;
};

const isStopped = (quota: QuotaResponse | null): boolean =>
  (['direct', 'agent'] as const).some(
    (scope) => noticeFor(quota, scope)?.level === 'reached',
  );

/**
 * The listener that keeps the quota fresh: after each finished turn
 * (debounced), at once after a quota error, on focus at most every 5
 * minutes (every 15 s while an allowance is used up), and at the reset.
 * One per store.
 */
export function createUsageListener() {
  const listener = createListenerMiddleware();
  const usageOf = (state: unknown) => (state as UsageRootState).usage;

  listener.startListening({
    actionCreator: usageTurnFinished,
    effect: async (_action, api) => {
      api.cancelActiveListeners();
      await api.delay(TURN_DEBOUNCE_MS);
      // An unlimited person has nothing to show; focus still catches a new limit.
      if (isUnlimited(usageOf(api.getState()))) return;
      api.dispatch(loadUsage() as never);
    },
  });

  listener.startListening({
    actionCreator: usageQuotaError,
    effect: (_action, api) => {
      api.dispatch(loadUsage({ force: true }) as never);
    },
  });

  listener.startListening({
    actionCreator: usageFocused,
    effect: (_action, api) => {
      const { loadedAt, quota } = usageOf(api.getState());
      const every = isStopped(quota)
        ? STOPPED_FOCUS_REFETCH_MS
        : FOCUS_REFETCH_MS;
      if (loadedAt !== null && Date.now() - loadedAt < every) return;
      api.dispatch(loadUsage() as never);
    },
  });

  listener.startListening({
    actionCreator: loadUsage.fulfilled,
    effect: async (_action, api) => {
      api.cancelActiveListeners();
      const at = nextReset(usageOf(api.getState()).quota);
      // A reset already behind us (a skewed clock) would read again at once,
      // forever; focus and the next turn cover that case.
      if (at === null || at + RESET_SLACK_MS <= Date.now()) return;
      for (;;) {
        const wait = at + RESET_SLACK_MS - Date.now();
        if (wait <= 0) break;
        await api.delay(Math.min(wait, MAX_WAIT_MS));
      }
      api.dispatch(loadUsage({ force: true }) as never);
    },
  });

  return listener;
}

/** The listener `store.ts` registers. */
export const usageListenerMiddleware = createUsageListener();

let boundDispatch: ((action: unknown) => unknown) | null = null;

/**
 * Lets code outside Redux (the chat stream handlers) tell the slice a turn
 * ended. `store.ts` connects its store; tests connect theirs, or null.
 */
export function connectUsage(
  store: { dispatch: (action: never) => unknown } | null,
): void {
  boundDispatch = store ? (action) => store.dispatch(action as never) : null;
}

/** A chat turn ended; the quota is read again 30 s after the last one. */
export function noteTurnFinished(): void {
  boundDispatch?.(usageTurnFinished());
}

/** A chat was stopped for the allowance; the quota is read again at once. */
export function noteQuotaError(): void {
  boundDispatch?.(usageQuotaError());
}

const percentOf = (ratio: number): number =>
  // Rounded first so float noise (0.29 * 100 = 28.999…) doesn't drop a point.
  Math.min(100, Math.floor(Math.round(ratio * 100 * 1e6) / 1e6));

/**
 * The near/reached notice for a chat, worked out the server's way from the
 * buckets that chat spends from (`all` and its scope), so a used-up agent
 * allowance never stops a chat without one. Without a scope, the server's
 * own notice (every bucket).
 *
 * Args:
 *   quota: The quota answer, or null before one arrived.
 *   scope: `direct` or `agent`; left out for the server's notice.
 *
 * Returns:
 *   The notice, or null under 80% or when unlimited.
 */
export function noticeFor(
  quota: QuotaResponse | null,
  scope?: UsageScope,
): QuotaNotice | null {
  if (!quota) return null;
  if (!scope) return quota.notice;
  let best: { ratio: number; notice: Omit<QuotaNotice, 'level'> } | null = null;
  for (const bucket of quota.buckets) {
    if (bucket.bucket !== 'all' && bucket.bucket !== scope) continue;
    for (const budget of ['tokens', 'cost'] as const) {
      const { limit, used } = bucket[budget];
      if (limit === null || limit === undefined) continue;
      const ratio = limit > 0 ? used / limit : 1;
      if (best && ratio <= best.ratio) continue;
      best = {
        ratio,
        notice: {
          percent: percentOf(ratio),
          bucket: bucket.bucket,
          budget,
          resets_at: bucket.resets_at,
        },
      };
    }
  }
  if (!best || best.notice.percent < NEAR_PERCENT) return null;
  return { level: best.ratio >= 1 ? 'reached' : 'near', ...best.notice };
}

// A store without the slice (a component test's) reads as nothing loaded.
export const selectUsage = (state: { usage?: UsageState }): UsageState =>
  state.usage ?? initialState;
export const selectQuota = (state: {
  usage?: UsageState;
}): QuotaResponse | null => state.usage?.quota ?? null;
/** What the person's used-up allowance stopped; null unless reached. */
export const selectUsagePaused = (state: {
  usage?: UsageState;
}): QuotaPaused | null => state.usage?.quota?.paused ?? null;

const noticeSelectors = {
  all: createSelector([selectQuota], (quota) => noticeFor(quota)),
  direct: createSelector([selectQuota], (quota) => noticeFor(quota, 'direct')),
  agent: createSelector([selectQuota], (quota) => noticeFor(quota, 'agent')),
};

/**
 * The near/reached notice (memoised): for a chat's scope, or the server's
 * over every bucket.
 */
export const selectUsageNotice = (
  state: { usage?: UsageState },
  scope?: UsageScope,
): QuotaNotice | null => noticeSelectors[scope ?? 'all'](state);
