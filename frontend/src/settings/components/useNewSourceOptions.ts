import { useCallback, useEffect, useState } from 'react';

import userService from '../../api/services/userService';
import {
  DEFAULT_RETRIEVAL_OPTIONS,
  type RetrievalOptionsValue,
  configToOptions,
} from './RetrievalOptions';

/**
 * The retrieval options of a new-source form. They start from the built-in
 * defaults and switch to the admin's defaults for new sources
 * (GET /api/sources/defaults) when those load, unless the user has already
 * changed the form; `reset` returns the form to them. The form sends its
 * whole retrieval block, so this is what makes the admin's defaults apply.
 * Nothing is fetched until `enabled`.
 */
export default function useNewSourceOptions(
  token: string | null,
  enabled = true,
) {
  const [defaults, setDefaults] = useState<RetrievalOptionsValue>(
    DEFAULT_RETRIEVAL_OPTIONS,
  );
  const [value, setValue] = useState<RetrievalOptionsValue>(
    DEFAULT_RETRIEVAL_OPTIONS,
  );

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    userService
      .getSourceDefaults(token)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (cancelled || !data?.retrieval) return;
        const loaded = configToOptions({ retrieval: data.retrieval });
        setDefaults(loaded);
        setValue((current) =>
          current === DEFAULT_RETRIEVAL_OPTIONS ? loaded : current,
        );
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [enabled, token]);

  const reset = useCallback(() => setValue(defaults), [defaults]);

  return { value, setValue, reset };
}
