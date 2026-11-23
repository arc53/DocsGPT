import { DRAFTER_STARTERS, type DrafterStarter } from '../drafter/starters';

/**
 * How the New agent modal asks the new-agent form to open Draft with DocsGPT:
 * with a description to send, from a starting point, or with neither (the
 * drawer's first screen). Carried in the router's state, so a reload or a
 * shared link never repeats it.
 */
export type DraftStart = { text?: string; starter?: DrafterStarter };

/** The router state that carries a draft start to the new-agent form. */
export const draftStartState = (start: DraftStart) => ({ draftStart: start });

/**
 * Read a draft start back from the router's state.
 *
 * Args:
 *   state: `location.state`, whatever it holds.
 *
 * Returns:
 *   The start with only what is valid in it, or null when the state has none.
 */
export function readDraftStart(state: unknown): DraftStart | null {
  if (typeof state !== 'object' || state === null) return null;
  const raw = (state as { draftStart?: unknown }).draftStart;
  if (typeof raw !== 'object' || raw === null) return null;
  const { text, starter } = raw as { text?: unknown; starter?: unknown };
  const start: DraftStart = {};
  if (typeof text === 'string' && text.trim()) start.text = text.trim();
  if (DRAFTER_STARTERS.some(({ key }) => key === starter))
    start.starter = starter as DrafterStarter;
  return start;
}
