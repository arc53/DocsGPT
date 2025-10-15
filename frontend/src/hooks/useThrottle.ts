import { useCallback, useRef, useEffect, useState } from 'react';
import { throttle, debounce } from 'lodash';

/**
 * Hook that returns a throttled version of the provided function.
 * Useful for API calls that should be limited to execute at most once per delay period.
 *
 * @param callback - The function to throttle
 * @param delay - Minimum delay between executions in milliseconds
 * @param deps - Dependencies array for the callback
 * @returns Throttled function
 */
export function useThrottle<T extends (...args: any[]) => any>(
  callback: T,
  delay: number,
  deps: React.DependencyList = [],
): T {
  const throttledRef = useRef<ReturnType<typeof throttle> | null>(null);

  const throttledCallback = useCallback(
    (...args: Parameters<T>) => {
      if (!throttledRef.current) {
        throttledRef.current = throttle(callback, delay);
      }
      return throttledRef.current(...args);
    },
    [callback, delay, ...deps],
  ) as T;

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (throttledRef.current) {
        throttledRef.current.cancel();
      }
    };
  }, []);

  return throttledCallback;
}

/**
 * Hook that returns a debounced version of the provided function.
 * Useful for search inputs and form field changes to delay execution until after user stops typing.
 *
 * @param callback - The function to debounce
 * @param delay - Delay in milliseconds before execution after last call
 * @param deps - Dependencies array for the callback
 * @returns Debounced function
 */
export function useDebounce<T extends (...args: any[]) => any>(
  callback: T,
  delay: number,
  deps: React.DependencyList = [],
): T {
  const debouncedRef = useRef<ReturnType<typeof debounce> | null>(null);

  const debouncedCallback = useCallback(
    (...args: Parameters<T>) => {
      if (!debouncedRef.current) {
        debouncedRef.current = debounce(callback, delay);
      }
      return debouncedRef.current(...args);
    },
    [callback, delay, ...deps],
  ) as T;

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (debouncedRef.current) {
        debouncedRef.current.cancel();
      }
    };
  }, []);

  return debouncedCallback;
}

/**
 * Hook for debounced values (commonly used for search terms).
 * Returns the debounced value that updates after the specified delay.
 *
 * @param value - The value to debounce
 * @param delay - Delay in milliseconds
 * @returns Debounced value
 */
export function useDebouncedValue<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);
  const debouncedSetter = useDebounce(setDebouncedValue, delay, []);

  useEffect(() => {
    debouncedSetter(value);
  }, [value, debouncedSetter]);

  return debouncedValue;
}
