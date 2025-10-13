import { debounce, throttle } from 'lodash';

/**
 * Debounces API calls to prevent excessive requests during high-frequency user actions.
 * Useful for search inputs, form field changes, and other user typing actions.
 *
 * @param fn - The function to debounce
 * @param delay - Delay in milliseconds (default: 500ms)
 * @returns Debounced function that delays execution until after the specified delay
 */
export const debounceAPI = <T extends (...args: any[]) => void>(
  fn: T,
  delay = 500,
) => debounce(fn, delay);

/**
 * Throttles API calls to limit execution frequency for spaced actions.
 * Useful for scroll handlers, "load more" buttons, and periodic refresh actions.
 *
 * @param fn - The function to throttle
 * @param delay - Minimum delay between executions in milliseconds (default: 2000ms)
 * @returns Throttled function that ensures execution at most once per delay period
 */
export const throttleAPI = <T extends (...args: any[]) => void>(
  fn: T,
  delay = 2000,
) => throttle(fn, delay);

/**
 * Creates a debounced version of an async function for API calls.
 * Handles promise-based functions while maintaining debouncing behavior.
 *
 * @param fn - The async function to debounce
 * @param delay - Delay in milliseconds (default: 500ms)
 * @returns Debounced async function
 */
export const debounceAsyncAPI = <T extends (...args: any[]) => Promise<any>>(
  fn: T,
  delay = 500,
) => {
  return debounce(fn, delay);
};

/**
 * Creates a throttled version of an async function for API calls.
 * Handles promise-based functions while maintaining throttling behavior.
 *
 * @param fn - The async function to throttle
 * @param delay - Minimum delay between executions in milliseconds (default: 2000ms)
 * @returns Throttled async function
 */
export const throttleAsyncAPI = <T extends (...args: any[]) => Promise<any>>(
  fn: T,
  delay = 2000,
) => {
  return throttle(fn, delay);
};
