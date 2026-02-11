import { useEffect, useMemo, useRef } from 'react';
import debounce from 'lodash/debounce';

/**
 * A hook that returns a debounced version of the provided callback.
 *
 * @param callback - The function to debounce
 * @param delay - The number of milliseconds to delay (default: 300)
 * @returns A debounced version of the callback
 */
export function useDebounce<T extends (...args: any[]) => void>(
  callback: T,
  delay = 300,
) {
  const callbackRef = useRef(callback);

  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  const debouncedFn = useMemo(
    () =>
      debounce((...args: Parameters<T>) => {
        callbackRef.current(...args);
      }, delay),
    [delay],
  );

  useEffect(() => {
    return () => {
      debouncedFn.cancel();
    };
  }, [debouncedFn]);

  return debouncedFn;
}

export default useDebounce;
