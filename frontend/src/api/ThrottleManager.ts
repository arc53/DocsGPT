import { throttle, debounce, ThrottleSettings, DebounceSettings } from 'lodash';

// ─── Error types ─────────────────────────────────────────────────────────────

export enum ThrottleError {
  THROTTLED = 'THROTTLED',
  DEBOUNCED = 'DEBOUNCED',
  ABORTED = 'ABORTED',
  DEDUPLICATED = 'DEDUPLICATED',
}

export interface ThrottleRejection {
  code: ThrottleError;
  message: string;
}

export function isThrottleRejection(err: unknown): err is ThrottleRejection {
  return (
    typeof err === 'object' &&
    err !== null &&
    'code' in err &&
    Object.values(ThrottleError).includes((err as ThrottleRejection).code)
  );
}

// ─── In-flight tracking ──────────────────────────────────────────────────────

interface InFlightEntry<T = unknown> {
  promise: Promise<T>;
  controller: AbortController;
  refCount: number;
}

// ─── ThrottleManager ─────────────────────────────────────────────────────────

/**
 * Utility class that wraps lodash throttle/debounce and provides
 * request deduplication with reference-counted AbortSignal coordination.
 *
 * Design goals:
 *  - Keep apiClient (`client.ts`) completely untouched.
 *  - Throttled / debounced calls reject with a clear `ThrottleRejection`
 *    so the UI can show "Please wait…" instead of silently dropping.
 *  - Deduplication prevents identical in-flight requests from hitting
 *    the network twice.
 *  - AbortSignal coordination uses reference counting: the shared
 *    AbortController is only aborted when *every* caller has signalled
 *    abort (or unmounted).
 */
export class ThrottleManager {
  private inFlightRequests = new Map<string, InFlightEntry>();

  // ── Key generation ───────────────────────────────────────────────────────

  /**
   * Generates a stable, deterministic cache key for deduplication.
   *
   * Handles non-serializable objects:
   *  - `FormData` → sorted [key, stringified-value] pairs
   *  - `File`     → "file:<name>:<size>"
   *  - Everything else → JSON.stringify
   */
  public static generateKey(url: string, options: any = {}): string {
    const { method = 'GET', body, params } = options;

    let bodyKey = '';
    if (body instanceof FormData) {
      const entries: [string, string][] = [];
      body.forEach((value, key) => {
        if (value instanceof File) {
          entries.push([key, `file:${value.name}:${value.size}`]);
        } else {
          entries.push([key, String(value)]);
        }
      });
      bodyKey = JSON.stringify(entries.sort((a, b) => a[0].localeCompare(b[0])));
    } else if (body !== undefined && body !== null) {
      bodyKey = typeof body === 'string' ? body : JSON.stringify(body);
    }

    const paramsKey = params
      ? JSON.stringify(
          typeof params === 'object' ? params : String(params),
        )
      : '';

    return `${method}:${url}:${paramsKey}:${bodyKey}`;
  }

  // ── Throttle wrapper ─────────────────────────────────────────────────────

  /**
   * Returns a throttled version of `fn` (lodash throttle under the hood).
   *
   * When a call is suppressed by the throttle window the returned promise
   * **rejects** with `{ code: ThrottleError.THROTTLED, message: … }` so
   * the caller can surface a "Please wait…" message.
   */
  public throttle<T extends (...args: any[]) => any>(
    fn: T,
    wait: number,
    options?: ThrottleSettings,
  ): (...args: Parameters<T>) => Promise<ReturnType<T>> {
    // Track invocation count so we can distinguish "actually ran" from
    // "returned cached result".
    let invocationId = 0;

    const throttled = throttle(
      (...args: Parameters<T>) => {
        invocationId++;
        return { id: invocationId, result: fn(...args) };
      },
      wait,
      options,
    );

    let lastSeenId = 0;

    return (...args: Parameters<T>) => {
      const wrapped = throttled(...args);

      // lodash throttle returns `undefined` when the call is suppressed
      // on the trailing edge (if trailing is disabled).
      if (wrapped === undefined) {
        return Promise.reject<ReturnType<T>>({
          code: ThrottleError.THROTTLED,
          message: `Request throttled – please wait ${wait}ms between calls.`,
        } satisfies ThrottleRejection);
      }

      const { id, result } = wrapped;

      if (id === lastSeenId) {
        // The throttle returned a cached result from the previous invocation.
        return Promise.reject<ReturnType<T>>({
          code: ThrottleError.THROTTLED,
          message: `Request throttled – please wait ${wait}ms between calls.`,
        } satisfies ThrottleRejection);
      }

      lastSeenId = id;
      return Promise.resolve(result as ReturnType<T>);
    };
  }

  // ── Debounce wrapper ─────────────────────────────────────────────────────

  /**
   * Returns a debounced version of `fn` (lodash debounce under the hood).
   *
   * Intermediate calls reject with `ThrottleError.DEBOUNCED`.
   * Only the *final* trailing call resolves with the real result.
   */
  public debounce<T extends (...args: any[]) => any>(
    fn: T,
    wait: number,
    options?: DebounceSettings,
  ): (...args: Parameters<T>) => Promise<ReturnType<T>> {
    let currentResolve: ((v: ReturnType<T>) => void) | null = null;
    let currentReject: ((reason: ThrottleRejection) => void) | null = null;

    const debounced = debounce((...args: Parameters<T>) => {
      const result = fn(...args);
      if (currentResolve) {
        currentResolve(result);
        currentResolve = null;
        currentReject = null;
      }
    }, wait, options);

    return (...args: Parameters<T>) => {
      // If a previous debounced call is still pending, reject it.
      if (currentReject) {
        currentReject({
          code: ThrottleError.DEBOUNCED,
          message: 'Request debounced – a newer call superseded this one.',
        });
      }

      return new Promise<ReturnType<T>>((resolve, reject) => {
        currentResolve = resolve;
        currentReject = reject;
        debounced(...args);
      });
    };
  }

  // ── Request deduplication ────────────────────────────────────────────────

  /**
   * Deduplicates identical in-flight requests.
   *
   * If a request with the same `key` is already in progress, the caller
   * shares the existing promise. AbortSignal coordination is handled via
   * reference counting:
   *
   *  - Each caller increments `refCount`.
   *  - When a caller's `externalSignal` fires `abort`, `refCount` is
   *    decremented.
   *  - The shared `AbortController` is only aborted when `refCount`
   *    reaches zero (i.e. *all* callers have aborted / unmounted).
   *
   * This means: Component A and B share a deduplicated request. If A
   * unmounts and calls `abort()`, B's request continues. Only when B
   * *also* aborts (or the request completes) does the controller fire.
   */
  public async dedupe<T>(
    key: string,
    requestFn: (signal: AbortSignal) => Promise<T>,
    externalSignal?: AbortSignal,
  ): Promise<T> {
    let entry = this.inFlightRequests.get(key) as InFlightEntry<T> | undefined;

    if (!entry) {
      const controller = new AbortController();
      const promise = requestFn(controller.signal).finally(() => {
        this.inFlightRequests.delete(key);
      });

      entry = { promise, controller, refCount: 0 };
      this.inFlightRequests.set(key, entry as InFlightEntry);
    }

    // Increment reference count for this caller.
    entry.refCount++;

    if (externalSignal) {
      const createAbortError = () => {
        const err = new Error('Aborted') as Error & { code: ThrottleError; name: string };
        err.name = 'AbortError';
        err.code = ThrottleError.ABORTED;
        return err;
      };

      // Already aborted before we even started.
      if (externalSignal.aborted) {
        this.releaseRef(key, entry);
        throw createAbortError();
      }

      const onAbort = () => {
        this.releaseRef(key, entry!);
      };

      externalSignal.addEventListener('abort', onAbort, { once: true });

      try {
        return await Promise.race([
          entry.promise,
          new Promise<T>((_, reject) => {
            if (externalSignal.aborted) {
              reject(createAbortError());
            }
            externalSignal.addEventListener(
              'abort',
              () => {
                reject(createAbortError());
              },
              { once: true },
            );
          }),
        ]);
      } finally {
        externalSignal.removeEventListener('abort', onAbort);
      }
    }

    return entry.promise;
  }

  // ── Helpers ──────────────────────────────────────────────────────────────

  /**
   * Decrement the reference count for an in-flight entry.
   * When refCount reaches 0, abort the underlying controller and clean up.
   */
  private releaseRef(key: string, entry: InFlightEntry): void {
    entry.refCount--;
    if (entry.refCount <= 0) {
      entry.controller.abort();
      this.inFlightRequests.delete(key);
    }
  }

  /**
   * Returns the number of currently in-flight deduplicated requests.
   * Useful for debugging / dev-tools integration.
   */
  public get pendingCount(): number {
    return this.inFlightRequests.size;
  }

  /**
   * Cancels *all* in-flight requests and clears the cache.
   * Intended for use in global teardown or hard navigation.
   */
  public cancelAll(): void {
    for (const [, entry] of this.inFlightRequests) {
      entry.controller.abort();
    }
    this.inFlightRequests.clear();
  }
}

/** Singleton instance shared across the application. */
export const throttleManager = new ThrottleManager();
