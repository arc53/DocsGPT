import { useEffect, useRef, useState } from 'react';

import userService from '../api/services/userService';
import { DEFAULT_WEB_PAGES, MAX_WEB_PAGES, type WebsiteDraft } from './website';

/**
 * A whole-site Website source's page limit: its default and the admin's cap
 * (WEB_DEFAULT_PAGES, WEB_MAX_PAGES from /api/config). Falls back to the
 * shipped defaults until the config arrives or when an older backend lacks
 * them; the backend clamps either way.
 */
export default function useWebPageLimits() {
  const [limits, setLimits] = useState({
    defaultPages: DEFAULT_WEB_PAGES,
    maxPages: MAX_WEB_PAGES,
  });

  useEffect(() => {
    let cancelled = false;
    userService
      .getConfig()
      .then((response) => response.json())
      .then((config) => {
        if (cancelled) return;
        const defaultPages = Number(config?.web_default_pages);
        const maxPages = Number(config?.web_max_pages);
        const cap = maxPages > 0 ? maxPages : MAX_WEB_PAGES;
        setLimits({
          // Never past the cap (WEB_MAX_PAGES set below WEB_DEFAULT_PAGES),
          // so the form opens valid.
          defaultPages: Math.min(
            defaultPages > 0 ? defaultPages : DEFAULT_WEB_PAGES,
            cap,
          ),
          maxPages: cap,
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return limits;
}

/**
 * Moves a draft's page limit to the admin's default when /api/config answers
 * after the draft was made (it starts on the shipped fallback), unless the
 * user already changed it.
 *
 * @param defaultPages The current default (`useWebPageLimits().defaultPages`).
 * @param setDraft The draft's setter.
 */
export function useReseedMaxPages(
  defaultPages: number,
  setDraft: React.Dispatch<React.SetStateAction<WebsiteDraft>>,
) {
  const seededRef = useRef(defaultPages);
  useEffect(() => {
    const previous = seededRef.current;
    if (previous === defaultPages) return;
    seededRef.current = defaultPages;
    setDraft((draft) =>
      draft.maxPages === previous
        ? { ...draft, maxPages: defaultPages }
        : draft,
    );
  }, [defaultPages, setDraft]);
}
