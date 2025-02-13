import { useEffect, RefObject, useState } from 'react';

export function useOutsideAlerter<T extends HTMLElement>(
  ref: RefObject<T>,
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
  }, [ref, ...additionalDeps]);
}

export function useMediaQuery() {
  const mobileQuery = '(max-width: 768px)';
  const darkModeQuery = '(prefers-color-scheme: dark)'; // Detect dark mode
  const desktopQuery = '(min-width: 960px)';
  const [isMobile, setIsMobile] = useState(false);
  const [isDesktop, setIsDesktop] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(false);

  useEffect(() => {
    const mobileMedia = window.matchMedia(mobileQuery);
    const desktopMedia = window.matchMedia(desktopQuery);
    const darkModeMedia = window.matchMedia(darkModeQuery);

    const updateMediaQueries = () => {
      setIsMobile(mobileMedia.matches);
      setIsDesktop(desktopMedia.matches);
      setIsDarkMode(darkModeMedia.matches);
    };

    updateMediaQueries();

    const listener = () => updateMediaQueries();
    window.addEventListener('resize', listener);

    return () => {
      window.removeEventListener('resize', listener);
    };
  }, [mobileQuery, desktopQuery, darkModeQuery]);

  return { isMobile, isDesktop, isDarkMode };
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
  delay = 500,
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
