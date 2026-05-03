import { describe, it, expect, beforeEach, vi } from 'vitest';
import { ThrottleManager, ThrottleError } from '../ThrottleManager';

describe('ThrottleManager', () => {
  let throttleManager: ThrottleManager;

  beforeEach(() => {
    throttleManager = new ThrottleManager();
    vi.useFakeTimers();
  });

  afterEach(() => {
    throttleManager.cancelAll();
    vi.restoreAllMocks();
  });

  describe('generateKey', () => {
    it('should generate a consistent key for primitive bodies', () => {
      const key1 = ThrottleManager.generateKey('/api/test', { method: 'POST', body: 'test' });
      const key2 = ThrottleManager.generateKey('/api/test', { method: 'POST', body: 'test' });
      expect(key1).toBe(key2);
      expect(key1).toBe('POST:/api/test::test');
    });

    it('should generate a consistent key for object bodies', () => {
      const key1 = ThrottleManager.generateKey('/api/test', { method: 'POST', body: { a: 1 } });
      const key2 = ThrottleManager.generateKey('/api/test', { method: 'POST', body: { a: 1 } });
      expect(key1).toBe(key2);
      expect(key1).toBe('POST:/api/test::{"a":1}');
    });
  });

  describe('throttle', () => {
    it('should throttle function calls', async () => {
      const fn = vi.fn().mockReturnValue('result');
      const throttledFn = throttleManager.throttle(fn, 1000);

      const promise1 = throttledFn();
      const promise2 = throttledFn();

      await expect(promise1).resolves.toBe('result');
      await expect(promise2).rejects.toEqual({
        code: ThrottleError.THROTTLED,
        message: 'Request throttled – please wait 1000ms between calls.',
      });

      expect(fn).toHaveBeenCalledTimes(1);
    });
  });

  describe('dedupe', () => {
    it('should deduplicate identical concurrent requests', async () => {
      let callCount = 0;
      const requestFn = async (signal: AbortSignal) => {
        callCount++;
        await new Promise((resolve) => setTimeout(resolve, 100));
        return 'success';
      };

      const promise1 = throttleManager.dedupe('key1', requestFn);
      const promise2 = throttleManager.dedupe('key1', requestFn);

      expect(throttleManager.pendingCount).toBe(1);

      vi.advanceTimersByTime(100);

      const [res1, res2] = await Promise.all([promise1, promise2]);

      expect(res1).toBe('success');
      expect(res2).toBe('success');
      expect(callCount).toBe(1);
      expect(throttleManager.pendingCount).toBe(0);
    });

    it('should handle AbortSignal reference counting correctly', async () => {
      const abortFn = vi.fn();
      const requestFn = async (signal: AbortSignal) => {
        signal.addEventListener('abort', abortFn);
        await new Promise((resolve) => setTimeout(resolve, 100));
        return 'success';
      };

      const controller1 = new AbortController();
      const controller2 = new AbortController();

      const promise1 = throttleManager.dedupe('key1', requestFn, controller1.signal);
      const promise2 = throttleManager.dedupe('key1', requestFn, controller2.signal);

      // Abort first request
      controller1.abort();

      await expect(promise1).rejects.toMatchObject({ code: ThrottleError.ABORTED });
      
      // The internal request should not be aborted yet because controller2 is still active
      expect(abortFn).not.toHaveBeenCalled();

      // Abort second request
      controller2.abort();

      await expect(promise2).rejects.toMatchObject({ code: ThrottleError.ABORTED });
      
      // Now the internal request should be aborted
      expect(abortFn).toHaveBeenCalled();
    });

    it('should not abort the shared request if it completes before the last signal aborts', async () => {
      const abortFn = vi.fn();
      const requestFn = async (signal: AbortSignal) => {
        signal.addEventListener('abort', abortFn);
        await new Promise((resolve) => setTimeout(resolve, 50));
        return 'success';
      };

      const controller1 = new AbortController();
      const controller2 = new AbortController();

      const promise1 = throttleManager.dedupe('key1', requestFn, controller1.signal);
      const promise2 = throttleManager.dedupe('key1', requestFn, controller2.signal);

      // Abort first request
      controller1.abort();

      await expect(promise1).rejects.toMatchObject({ code: ThrottleError.ABORTED });

      // Let the request complete
      vi.advanceTimersByTime(50);

      const res2 = await promise2;
      expect(res2).toBe('success');

      // Now abort second request after completion
      controller2.abort();

      // The internal controller should not have been aborted
      expect(abortFn).not.toHaveBeenCalled();
    });
  });
});
