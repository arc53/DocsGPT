import { useEffect, RefObject } from 'react';

export function useOutsideAlerter<T extends HTMLElement>(
  ref: RefObject<T>,
  handler: () => void,
  additionalDeps: unknown[],
) {
  useEffect(() => {
    function handleClickOutside(this: Document, event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        handler();
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [ref, ...additionalDeps]);
}
