import React from 'react';

import { fetchAgentStarters } from '../requests/startersApi';

/** A slower answer is dropped: the questions would appear mid-read. */
const STARTERS_TIMEOUT_MS = 10_000;

/**
 * The agent's starters, fetched once per `apiKey` and `apiHost` while
 * `enabled`. Empty until they arrive, and stays empty when the request fails
 * or runs past {@link STARTERS_TIMEOUT_MS}.
 */
export function useAgentStarters(
  apiKey: string,
  apiHost: string,
  enabled: boolean,
): string[] {
  const [starters, setStarters] = React.useState<string[]>([]);

  React.useEffect(() => {
    // Another agent's questions must not linger while this one's load.
    setStarters([]);
    if (!enabled || !apiKey) return;

    const controller = new AbortController();
    const timeout = window.setTimeout(
      () => controller.abort(),
      STARTERS_TIMEOUT_MS,
    );
    fetchAgentStarters(apiKey, apiHost, controller.signal).then((list) => {
      if (!controller.signal.aborted) setStarters(list);
    });
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [apiKey, apiHost, enabled]);

  return starters;
}
