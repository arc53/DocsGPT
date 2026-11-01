import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import { selectToken } from '../preferences/preferenceSlice';
import { type DrafterConfig, getDrafterConfig } from './drafterApi';

// One read per session token: every form with a wand asks the same question.
const cache = new Map<string, Promise<DrafterConfig>>();

/** Forget the cached config (tests, and after the task model changes). */
export function resetDrafterConfigCache(): void {
  cache.clear();
}

/**
 * The drafter's config for the signed-in user, read once per token. While it
 * loads, and whenever it can't be read, it is `null`, so every wand entry
 * point stays hidden until the server says the drafter is on.
 *
 * Returns:
 *   The config, or null while unknown.
 */
export function useDrafterConfig(): DrafterConfig | null {
  const token = useSelector(selectToken);
  const key = token ?? '';
  const [config, setConfig] = useState<{
    key: string;
    value: DrafterConfig;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    let pending = cache.get(key);
    if (!pending) {
      pending = getDrafterConfig(token);
      cache.set(key, pending);
    }
    void pending.then((value) => {
      if (!cancelled) setConfig({ key, value });
    });
    return () => {
      cancelled = true;
    };
  }, [key, token]);

  return config?.key === key ? config.value : null;
}
