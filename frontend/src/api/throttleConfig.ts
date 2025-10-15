import { throttle, debounce } from 'lodash';

// Centralized throttling and debouncing configuration
export const API_THROTTLE_CONFIG = {
  // Analytics API calls - throttled to avoid excessive requests during filter changes
  ANALYTICS: 1500, // 1.5 seconds

  // Search/filtering - debounced to wait for user to stop typing
  SEARCH: 500, // 0.5 seconds

  // Polling operations - throttled to limit refresh frequency
  POLLING: 2000, // 2 seconds

  // User interaction - throttled for repeated actions
  USER_ACTION: 1000, // 1 second
} as const;

// Cache for throttled/debounced functions to maintain single instances
const throttledFunctions = new Map<string, any>();
const debouncedFunctions = new Map<string, any>();

/**
 * Get or create a throttled version of a function with consistent timing
 * @param key - Unique identifier for the function
 * @param fn - Function to throttle
 * @param delay - Throttle delay in milliseconds
 * @returns Throttled function
 */
export function getThrottledFunction<T extends (...args: any[]) => any>(
  key: string,
  fn: T,
  delay: number,
): T {
  if (!throttledFunctions.has(key)) {
    throttledFunctions.set(key, throttle(fn, delay));
  }
  return throttledFunctions.get(key);
}

/**
 * Get or create a debounced version of a function with consistent timing
 * @param key - Unique identifier for the function
 * @param fn - Function to debounce
 * @param delay - Debounce delay in milliseconds
 * @returns Debounced function
 */
export function getDebouncedFunction<T extends (...args: any[]) => any>(
  key: string,
  fn: T,
  delay: number,
): T {
  if (!debouncedFunctions.has(key)) {
    debouncedFunctions.set(key, debounce(fn, delay));
  }
  return debouncedFunctions.get(key);
}

/**
 * Clear all cached throttled/debounced functions
 * Useful for cleanup in tests or when needed
 */
export function clearThrottleCache(): void {
  throttledFunctions.forEach((fn) => fn.cancel?.());
  debouncedFunctions.forEach((fn) => fn.cancel?.());
  throttledFunctions.clear();
  debouncedFunctions.clear();
}
