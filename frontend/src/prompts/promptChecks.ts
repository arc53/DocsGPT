import apiClient from '../api/client';
import endpoints from '../api/endpoints';
import { isString } from '../utils/wireGuards';
import type { PromptCheckFacts } from './promptCheckText';

/**
 * `POST /api/check_prompt`'s `checks`, malformed entries dropped: each needs
 * a code; its text, topic, variables and line are kept when well formed.
 *
 * Args:
 *   raw: The response's `checks`.
 *
 * Returns:
 *   The checks, in the server's order.
 */
export function readPromptChecks(raw: unknown): PromptCheckFacts[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item): PromptCheckFacts[] => {
    if (!item || typeof item !== 'object') return [];
    const value = item as Record<string, unknown>;
    if (!isString(value.code) || !value.code) return [];
    return [
      {
        code: value.code,
        text: isString(value.text) ? value.text : null,
        topic: isString(value.topic) ? value.topic : null,
        variables: Array.isArray(value.variables)
          ? value.variables.filter(isString)
          : [],
        line:
          typeof value.line === 'number' && Number.isInteger(value.line)
            ? value.line
            : null,
      },
    ];
  });
}

/**
 * The checks that need no model (placeholders, lines DocsGPT already adds,
 * a template that won't parse, tool variables, a template missing its
 * Boundaries or citations), from `POST /api/check_prompt`. They run with
 * the drafter off too.
 *
 * Args:
 *   content: The prompt's text.
 *   token: The session token.
 *   signal: Aborts a request a newer text replaced.
 *
 * Returns:
 *   The checks, or null when they couldn't be read (the hint then shows
 *   nothing).
 */
export async function checkPrompt(
  content: string,
  token: string | null,
  signal?: AbortSignal,
): Promise<PromptCheckFacts[] | null> {
  try {
    const response: Response = await apiClient.post(
      endpoints.USER.CHECK_PROMPT,
      { content },
      token,
      {},
      signal,
    );
    if (!response?.ok) return null;
    const data = (await response.json()) as { checks?: unknown };
    return readPromptChecks(data?.checks);
  } catch {
    return null;
  }
}
