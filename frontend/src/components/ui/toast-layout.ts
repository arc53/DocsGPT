import { createContext, useContext, useEffect, type RefObject } from 'react';

/**
 * Where the toast stack sits: in the bottom-right corner, or just above a
 * composer it would otherwise cover. A composer registers itself with
 * `useAvoidToasts`; the one `ToastViewport` measures every registered
 * element against its own column and rises above the highest one it
 * overlaps.
 */

/** Gap between the stack's box and the window's bottom edge; its p-2 adds 8px. */
export const TOAST_STACK_BOTTOM_PX = 16;
/** Room the stack leaves above itself for the page header. */
export const TOAST_STACK_TOP_RESERVE_PX = 72;

type Box = Pick<DOMRect, 'left' | 'right' | 'top' | 'width' | 'height'>;

export type ToastStackLayout = { bottom: number; maxHeight: number };

/**
 * The stack's bottom offset and the most height it may take.
 *
 * Args:
 *   stack: The stack's horizontal extent.
 *   avoid: The boxes it must not cover (composers); an empty box is one
 *     that is not laid out, and is skipped.
 *   viewportHeight: The window's inner height.
 */
export function toastStackLayout(
  stack: Pick<Box, 'left' | 'right'>,
  avoid: Box[],
  viewportHeight: number,
): ToastStackLayout {
  let bottom = TOAST_STACK_BOTTOM_PX;
  for (const box of avoid) {
    if (box.width === 0 || box.height === 0) continue;
    if (box.right <= stack.left || box.left >= stack.right) continue;
    bottom = Math.max(bottom, Math.round(viewportHeight - box.top));
  }
  return {
    bottom,
    maxHeight: Math.max(
      0,
      viewportHeight - bottom - TOAST_STACK_TOP_RESERVE_PX,
    ),
  };
}

/** The elements the toast stack keeps clear of, and who to tell when they change. */
export type ToastAvoidRegistry = {
  /** Add an element; returns its removal. */
  add: (element: HTMLElement) => () => void;
  elements: () => HTMLElement[];
  subscribe: (listener: () => void) => () => void;
};

export function createToastAvoidRegistry(): ToastAvoidRegistry {
  const elements = new Set<HTMLElement>();
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach((listener) => listener());
  return {
    add(element) {
      elements.add(element);
      notify();
      return () => {
        if (elements.delete(element)) notify();
      };
    },
    elements: () => Array.from(elements),
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/** Provided once around the app layout, next to its `ToastViewport`. */
export const ToastAvoidContext = createContext<ToastAvoidRegistry | null>(null);

/** Keep the toast stack off this element while it is mounted (a composer). */
export function useAvoidToasts(ref: RefObject<HTMLElement | null>): void {
  const registry = useContext(ToastAvoidContext);
  useEffect(() => {
    const element = ref.current;
    if (!registry || !element) return;
    return registry.add(element);
  }, [registry, ref]);
}
