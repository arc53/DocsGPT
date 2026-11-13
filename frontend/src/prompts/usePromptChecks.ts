import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import { selectToken } from '../preferences/preferenceSlice';
import { checkPrompt } from './promptChecks';
import type { PromptCheckFacts } from './promptCheckText';

/** How long the text rests before it is checked. */
export const PROMPT_CHECKS_DELAY_MS = 400;

/**
 * The no-model checks for a prompt's text, read once typing pauses
 * (`PROMPT_CHECKS_DELAY_MS`); a newer text aborts the request still out.
 * The last answer stays while the next one comes, so the hint doesn't
 * flicker as you type; a failed read shows nothing.
 *
 * Args:
 *   content: The prompt's text.
 *   enabled: False for a text no one can change (read-only, under review):
 *     nothing is read and nothing comes back.
 *
 * Returns:
 *   The checks, in the server's order.
 */
export function usePromptChecks(
  content: string,
  enabled: boolean,
): PromptCheckFacts[] {
  const token = useSelector(selectToken);
  const [checks, setChecks] = useState<PromptCheckFacts[]>([]);
  const active = enabled && content.trim() !== '';

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void checkPrompt(content, token, controller.signal).then((result) => {
        if (!controller.signal.aborted) setChecks(result ?? []);
      });
    }, PROMPT_CHECKS_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [active, content, token]);

  return active ? checks : [];
}
