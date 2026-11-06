import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import { selectToken } from '../preferences/preferenceSlice';
import { type DrafterConfig, getDrafterConfig } from './drafterApi';

// One read per session token: every form with a wand asks the same question.
const cache = new Map<string, Promise<DrafterConfig>>();

/** Forget the cached config (tests, and after the user's or the instance's task model changes). */
export function resetDrafterConfigCache(): void {
  cache.clear();
}

/**
 * Whether an answer is worth keeping. A failed read (`reason: 'unavailable'`)
 * never is: a network blip mustn't hide the wand until a reload.
 */
const keeps = (config: DrafterConfig): boolean =>
  config.reason !== 'unavailable';

/**
 * The drafter's config for a session token, read once per token and shared
 * with `useDrafterConfig`. For a component that has the token from its host
 * rather than the store. A read in flight is shared; an answer that may be
 * a failed read is not kept.
 *
 * Args:
 *   token: The session token.
 *
 * Returns:
 *   The config; `enabled: false` when it can't be read.
 */
export function loadDrafterConfig(
  token: string | null,
): Promise<DrafterConfig> {
  const key = token ?? '';
  const cached = cache.get(key);
  if (cached) return cached;
  const pending = getDrafterConfig(token).then((config) => {
    if (!keeps(config) && cache.get(key) === pending) cache.delete(key);
    return config;
  });
  cache.set(key, pending);
  return pending;
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
    void loadDrafterConfig(token).then((value) => {
      if (!cancelled) setConfig({ key, value });
    });
    return () => {
      cancelled = true;
    };
  }, [key, token]);

  return config?.key === key ? config.value : null;
}
