/**
 * Transport-layer middleware factory for the frontend API layer.
 */

export type FetchLike = (
  input: string,
  init?: RequestInit,
) => Promise<Response>;

export interface ThrottleConfig {
  maxConcurrentGlobal?: number;
  maxConcurrentPerRoute?: number;
  dedupe?: boolean;
  dedupeKey?: (url: string, init?: RequestInit) => string | false;
  debugLabel?: string;
}

const DEFAULT_MAX_CONCURRENT_GLOBAL = 8;
const DEFAULT_MAX_CONCURRENT_PER_ROUTE = 3;

type QueueItem = {
  run: () => void;
  signal?: AbortSignal;
  onAbort: () => void;
};

function routeKey(method: string, url: string): string {
  let pathname = url;
  try {
    pathname = new URL(url, 'http://_').pathname;
  } catch {
    pathname = url.split('?')[0];
  }
  return `${method.toUpperCase()} ${pathname}`;
}

function abortError(): DOMException {
  return new DOMException('The operation was aborted.', 'AbortError');
}

interface ThrottleState {
  perRouteQueues: Map<string, QueueItem[]>;
  inflightPerRoute: Map<string, number>;
  inflightGets: Map<string, Promise<Response>>;
  inflightGlobal: number;
}

function createState(): ThrottleState {
  return {
    perRouteQueues: new Map(),
    inflightPerRoute: new Map(),
    inflightGets: new Map(),
    inflightGlobal: 0,
  };
}

export function withThrottle(
  fetchLike: FetchLike,
  config: ThrottleConfig = {},
): FetchLike & { __reset: () => void } {
  const maxGlobal = config.maxConcurrentGlobal ?? DEFAULT_MAX_CONCURRENT_GLOBAL;
  const maxPerRoute =
    config.maxConcurrentPerRoute ?? DEFAULT_MAX_CONCURRENT_PER_ROUTE;
  const dedupeEnabled = config.dedupe !== false;
  const state = createState();

  // Toggle in DevTools with: localStorage.setItem('debug:throttle', '1')
  const isDebug = (): boolean => {
    try {
      return (
        typeof localStorage !== 'undefined' &&
        localStorage.getItem('debug:throttle') === '1'
      );
    } catch {
      return false;
    }
  };

  const log = (
    event: string,
    key: string,
    extra?: Record<string, unknown>,
  ): void => {
    if (!isDebug()) return;
    const queued = state.perRouteQueues.get(key)?.length ?? 0;
    const perRoute = state.inflightPerRoute.get(key) ?? 0;
    const tag = config.debugLabel
      ? `[throttle:${config.debugLabel}]`
      : '[throttle]';
    console.debug(
      `${tag} ${event} ${key} | inflight=${state.inflightGlobal}/${maxGlobal} route=${perRoute}/${maxPerRoute} queued=${queued}`,
      extra ?? '',
    );
  };

  const canDispatch = (key: string): boolean => {
    const perRoute = state.inflightPerRoute.get(key) ?? 0;
    return state.inflightGlobal < maxGlobal && perRoute < maxPerRoute;
  };

  const pumpQueues = (): void => {
    for (const [key, queue] of state.perRouteQueues) {
      while (queue.length > 0 && canDispatch(key)) {
        const item = queue.shift()!;
        item.signal?.removeEventListener('abort', item.onAbort);
        item.run();
      }
      if (queue.length === 0) state.perRouteQueues.delete(key);
    }
  };

  const enqueue = (key: string, item: QueueItem): void => {
    let queue = state.perRouteQueues.get(key);
    if (!queue) {
      queue = [];
      state.perRouteQueues.set(key, queue);
    }
    queue.push(item);
  };

  const acquireSlot = (key: string, signal?: AbortSignal): Promise<void> =>
    new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(abortError());
        return;
      }
      const item: QueueItem = {
        signal,
        run: () => {
          state.inflightGlobal += 1;
          state.inflightPerRoute.set(
            key,
            (state.inflightPerRoute.get(key) ?? 0) + 1,
          );
          resolve();
        },
        onAbort: () => {
          const queue = state.perRouteQueues.get(key);
          if (queue) {
            const idx = queue.indexOf(item);
            if (idx >= 0) queue.splice(idx, 1);
          }
          log('abort-queued', key);
          reject(abortError());
        },
      };
      const queued = state.perRouteQueues.get(key);
      if ((!queued || queued.length === 0) && canDispatch(key)) {
        item.run();
        log('dispatch', key);
        return;
      }
      signal?.addEventListener('abort', item.onAbort, { once: true });
      enqueue(key, item);
      log('queued', key);
    });

  const releaseSlot = (key: string): void => {
    state.inflightGlobal = Math.max(0, state.inflightGlobal - 1);
    const next = (state.inflightPerRoute.get(key) ?? 1) - 1;
    if (next <= 0) state.inflightPerRoute.delete(key);
    else state.inflightPerRoute.set(key, next);
    log('release', key);
    pumpQueues();
  };

  const wrapped = (async (url, init = {}) => {
    const method = (init.method ?? 'GET').toUpperCase();
    const signal = init.signal ?? undefined;
    const key = routeKey(method, url);

    // Dedupe is restricted to GETs without a caller-supplied AbortSignal:
    // sharing a single underlying fetch across waiters means an abort by one
    // caller would reject the others, which is not the contract callers expect.
    const customKey = config.dedupeKey?.(url, init);
    const dedupeAllowed =
      dedupeEnabled &&
      customKey !== false &&
      method === 'GET' &&
      !init.body &&
      !signal;
    const dedupeKey = typeof customKey === 'string' ? customKey : `GET ${url}`;

    if (dedupeAllowed) {
      const existing = state.inflightGets.get(dedupeKey);
      if (existing) {
        log('dedupe-hit', key, { dedupeKey });
        return existing.then((r) => r.clone());
      }
    }

    const run = async (): Promise<Response> => {
      await acquireSlot(key, signal);
      try {
        return await fetchLike(url, init);
      } finally {
        releaseSlot(key);
      }
    };

    if (dedupeAllowed) {
      const promise = run();
      state.inflightGets.set(dedupeKey, promise);
      promise.finally(() => {
        if (state.inflightGets.get(dedupeKey) === promise) {
          state.inflightGets.delete(dedupeKey);
        }
      });
      return promise.then((r) => r.clone());
    }

    return run();
  }) as FetchLike & { __reset: () => void };

  wrapped.__reset = () => {
    state.perRouteQueues.clear();
    state.inflightPerRoute.clear();
    state.inflightGets.clear();
    state.inflightGlobal = 0;
  };

  return wrapped;
}
