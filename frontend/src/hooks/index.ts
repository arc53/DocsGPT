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
  const [isDarkTheme, setIsDarkTheme] = useState<boolean>(localStorage.getItem('selectedTheme') === "Dark" || false);

  useEffect(() => {
    // Check if dark mode preference exists in local storage
    const savedMode: string | null = localStorage.getItem('selectedTheme');

    // Set dark mode based on local storage preference
    if (savedMode === 'Dark') {
      setIsDarkTheme(true);
      document.documentElement.classList.add('dark');
      document.documentElement.classList.add('dark:bg-raisin-black');
    } else {
      // If no preference found, set to default (light mode)
      setIsDarkTheme(false);
      document.documentElement.classList.remove('dark');
    }
  }, []);
  useEffect(() => {
    localStorage.setItem('selectedTheme', isDarkTheme ? 'Dark' : 'Light');
    if (isDarkTheme) {
      document.documentElement.classList.add('dark');
      document.documentElement.classList.add('dark:bg-raisin-black');
    }
    else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDarkTheme])
  //method to toggle theme
  const toggleTheme: any = () => {
    setIsDarkTheme(!isDarkTheme)
  };
  return [isDarkTheme, toggleTheme];
}