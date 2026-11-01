/**
 * The agent's starters: the questions its owner wrote for a new chat. Auth is
 * the agent key as `api_key` in the JSON body, so it stays out of URLs.
 *
 * Resolves to `[]` on any failure (an unknown key, a refused origin, a server
 * without the route): starters are optional, and a missing list must never
 * surface as an error.
 */
export async function fetchAgentStarters(
  apiKey: string,
  apiHost: string,
  signal?: AbortSignal,
): Promise<string[]> {
  try {
    const response = await fetch(`${apiHost}/api/agent_starters`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ api_key: apiKey }),
      signal,
    });
    if (!response.ok) return [];
    const data = await response.json().catch(() => null);
    const starters: unknown = data?.starters;
    if (!Array.isArray(starters)) return [];
    return starters.filter(
      (starter): starter is string => typeof starter === 'string',
    );
  } catch {
    return [];
  }
}
