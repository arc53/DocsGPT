import { useEffect, RefObject, useState } from 'react';

export function useOutsideAlerter<T extends HTMLElement>(
  ref: RefObject<T | null>,
  handler: () => void,
  additionalDeps: unknown[],
  handleEscapeKey?: boolean,
) {
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        handler();
      }
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        handler();
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    if (handleEscapeKey) {
      document.addEventListener('keydown', handleEscape);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      if (handleEscapeKey) {
        document.removeEventListener('keydown', handleEscape);
      }
    };
  }, [ref, handler, handleEscapeKey, ...additionalDeps]);
}

export function useMediaQuery() {
  const [isMobile, setIsMobile] = useState(
    () => window.matchMedia('(max-width: 768px)').matches,
  );
  const [isTablet, setIsTablet] = useState(
    () =>
      window.matchMedia('(max-width: 1023px)').matches &&
      !window.matchMedia('(max-width: 768px)').matches,
  );
  const [isDesktop, setIsDesktop] = useState(
    () => window.matchMedia('(min-width: 1024px)').matches,
  );

  useEffect(() => {
    const mobileMedia = window.matchMedia('(max-width: 768px)');
    const tabletMedia = window.matchMedia('(max-width: 1023px)');
    const desktopMedia = window.matchMedia('(min-width: 1024px)');

    const update = () => {
      setIsMobile(mobileMedia.matches);
      setIsTablet(tabletMedia.matches && !mobileMedia.matches);
      setIsDesktop(desktopMedia.matches);
    };

    mobileMedia.addEventListener('change', update);
    tabletMedia.addEventListener('change', update);
    desktopMedia.addEventListener('change', update);

    return () => {
      mobileMedia.removeEventListener('change', update);
      tabletMedia.removeEventListener('change', update);
      desktopMedia.removeEventListener('change', update);
    };
  }, []);

  return { isMobile, isTablet, isDesktop };
}

export function useDarkTheme() {
  const getSystemThemePreference = () => {
    return (
      window.matchMedia &&
      window.matchMedia('(prefers-color-scheme: dark)').matches
    );
  };

  const getInitialTheme = () => {
    const storedTheme = localStorage.getItem('selectedTheme');
    if (storedTheme === 'Dark' || storedTheme === 'Light') {
      return storedTheme === 'Dark';
    }
    return getSystemThemePreference();
  };

  const [isDarkTheme, setIsDarkTheme] = useState<boolean>(getInitialTheme());
  const [componentMounted, setComponentMounted] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = () => {
      if (localStorage.getItem('selectedTheme') === null) {
        setIsDarkTheme(mediaQuery.matches);
      }
    };

    mediaQuery.addListener(handleChange);
    return () => mediaQuery.removeListener(handleChange);
  }, []);

  useEffect(() => {
    localStorage.setItem('selectedTheme', isDarkTheme ? 'Dark' : 'Light');
    if (isDarkTheme) {
      document.body?.classList.add('dark');
    } else {
      document.body?.classList.remove('dark');
    }
    setComponentMounted(true);
  }, [isDarkTheme]);

  const toggleTheme = () => {
    setIsDarkTheme(!isDarkTheme);
  };

  return [isDarkTheme, toggleTheme, componentMounted] as const;
}

export function useLoaderState(
  initialState = false,
  delay = 250,
): [boolean, (value: boolean) => void] {
  const [state, setState] = useState<boolean>(initialState);

  const setLoaderState = (value: boolean) => {
    if (value) {
      setState(true);
    } else {
      // Only add delay when changing from true to false
      setTimeout(() => {
        setState(false);
      }, delay);
    }
  };

  return [state, setLoaderState];
}
