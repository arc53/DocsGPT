import { useEffect, useState } from 'react';

import userService from '../api/services/userService';
import { DEFAULT_WEB_PAGES, MAX_WEB_PAGES } from './website';

/**
 * A whole-site Website source's page limit: its default and the admin's cap
 * (WEB_DEFAULT_PAGES, WEB_MAX_PAGES from /api/config). Falls back to the
 * shipped defaults until the config arrives or when an older backend lacks
 * them; the backend clamps either way.
 *
 * @param enabled Fetch only while the form is open.
 */
export default function useWebPageLimits(enabled = true) {
  const [limits, setLimits] = useState({
    defaultPages: DEFAULT_WEB_PAGES,
    maxPages: MAX_WEB_PAGES,
  });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    userService
      .getConfig()
      .then((response) => response.json())
      .then((config) => {
        if (cancelled) return;
        const defaultPages = Number(config?.web_default_pages);
        const maxPages = Number(config?.web_max_pages);
        setLimits({
          defaultPages: defaultPages > 0 ? defaultPages : DEFAULT_WEB_PAGES,
          maxPages: maxPages > 0 ? maxPages : MAX_WEB_PAGES,
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return limits;
}
