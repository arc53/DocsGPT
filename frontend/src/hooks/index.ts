import {
  useCallback,
  useEffect,
  useRef,
  useState,
  RefObject,
} from 'react';

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
  const mobileQuery = '(max-width: 768px)';
  const tabletQuery = '(max-width: 1023px)';
  const desktopQuery = '(min-width: 1024px)';
  const [isMobile, setIsMobile] = useState(false);
  const [isTablet, setIsTablet] = useState(false);
  const [isDesktop, setIsDesktop] = useState(false);

  useEffect(() => {
    const mobileMedia = window.matchMedia(mobileQuery);
    const tabletMedia = window.matchMedia(tabletQuery);
    const desktopMedia = window.matchMedia(desktopQuery);

    const updateMediaQueries = () => {
      setIsMobile(mobileMedia.matches);
      setIsTablet(tabletMedia.matches && !mobileMedia.matches); // Tablet but not mobile
      setIsDesktop(desktopMedia.matches);
    };

    updateMediaQueries();

    const listener = () => updateMediaQueries();
    window.addEventListener('resize', listener);

    return () => {
      window.removeEventListener('resize', listener);
    };
  }, [mobileQuery, tabletQuery, desktopQuery]);

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

export function useDebouncedValue<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState<T>(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}

export function useDebouncedCallback<A extends unknown[]>(
  callback: (...args: A) => void,
  delay = 300,
): ((...args: A) => void) & { cancel: () => void } {
  const callbackRef = useRef(callback);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  const cancel = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => cancel, [cancel]);

  const debounced = useCallback(
    (...args: A) => {
      cancel();
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        callbackRef.current(...args);
      }, delay);
    },
    [delay, cancel],
  );

  return Object.assign(debounced, { cancel });
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
