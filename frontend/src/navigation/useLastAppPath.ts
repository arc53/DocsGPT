import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

import { getSectionForPath } from './sections';

/**
 * Remembers the last route outside any section, so leaving a section returns
 * the user to the conversation they were in rather than to a blank chat.
 */
export function useLastAppPath(fallback = '/') {
  const location = useLocation();
  const lastAppPath = useRef(fallback);

  useEffect(() => {
    if (!getSectionForPath(location.pathname))
      lastAppPath.current = `${location.pathname}${location.search}`;
  }, [location.pathname, location.search]);

  return lastAppPath;
}
