import { useEffect, RefObject, useState } from 'react';

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

// Use isMobile for checking if the width is in the expected mobile range (less than 768px)
// use IsDesktop for effects you explicitly only want when width is wider than 960px.
export function useMediaQuery() {
  const mobileQuery = '(max-width: 768px)';
  const desktopQuery = '(min-width: 960px)';
  const [isMobile, setIsMobile] = useState(false);
  const [isDesktop, setIsDesktop] = useState(false);

  useEffect(() => {
    const mobileMedia = window.matchMedia(mobileQuery);
    const desktopMedia = window.matchMedia(desktopQuery);
    const updateMediaQueries = () => {
      setIsMobile(mobileMedia.matches);
      setIsDesktop(desktopMedia.matches);
    };
    updateMediaQueries();
    const listener = () => updateMediaQueries();
    window.addEventListener('resize', listener);
    return () => {
      window.removeEventListener('resize', listener);
    };
  }, [mobileQuery, desktopQuery]);

  return { isMobile, isDesktop };
}
