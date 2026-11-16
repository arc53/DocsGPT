import { AGENTS_MANAGE_ROOT } from '../agents/paths';
import type { SwitchReason } from './workspaceSlice';

/** Query parameters that open a folder or one item of the old workspace. */
const ITEM_PARAMS = ['folder', 'source', 'tool', 'prompt'];

// The agents list and its filters; anything else under it is one agent's
// page or a new agent's form.
const AGENT_LISTS = new Set(
  ['', '/templates', '/mine', '/team', '/discovered'].map(
    (suffix) => `${AGENTS_MANAGE_ROOT}${suffix}`,
  ),
);

/**
 * Where the app goes when the workspace switches: a list page stays (without
 * an open folder or item, which belong to the old workspace); an item's page
 * goes to its list; a chat goes to a new chat. Personal settings, Activity,
 * the team pages and Admin stay.
 *
 * Args:
 *   pathname: The current path.
 *   search: The current query string, with or without its `?`.
 *
 * Returns:
 *   The path and query to land on.
 */
export function workspaceLandingPath(pathname: string, search = ''): string {
  if (pathname === '/c' || pathname.startsWith('/c/')) return '/c/new';
  if (pathname.startsWith('/agents/')) {
    if (/^\/agents\/[^/]+\/c\//.test(pathname)) return '/c/new';
    if (!AGENT_LISTS.has(pathname.replace(/\/$/, '')))
      return AGENTS_MANAGE_ROOT;
  }
  const params = new URLSearchParams(search);
  ITEM_PARAMS.forEach((name) => params.delete(name));
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

/** A workspace switch that waits for the page it navigated to. */
export type SwitchOnArrival = { id: string; reason: SwitchReason };

const SWITCH_STATE_KEY = 'workspaceSwitch';

/**
 * The location state that asks for a workspace switch once the page it is
 * navigated with has rendered (the layout's `useWorkspaceLanding` does it).
 * The router applies a new location in a transition, after a store update
 * has already rendered: a switch dispatched next to the navigation would
 * remount the page on the old address, which opens the old item again.
 *
 * Args:
 *   id: `personal` or a team id.
 *   reason: Why the app switches (see `switchWorkspace`).
 *
 * Returns:
 *   The `state` to navigate with.
 */
export function switchOnArrival(
  id: string,
  reason: SwitchReason = 'user',
): Record<string, SwitchOnArrival> {
  return { [SWITCH_STATE_KEY]: { id, reason } };
}

/**
 * The switch a location's state asks for, if any.
 *
 * Args:
 *   state: The location's `state`.
 *
 * Returns:
 *   The switch, or null.
 */
export function switchRequested(state: unknown): SwitchOnArrival | null {
  if (!state || typeof state !== 'object') return null;
  const request = (state as Record<string, unknown>)[SWITCH_STATE_KEY];
  if (!request || typeof request !== 'object') return null;
  const { id, reason } = request as Partial<SwitchOnArrival>;
  if (typeof id !== 'string' || !id) return null;
  return {
    id,
    reason: reason === 'link' || reason === 'lost' ? reason : 'user',
  };
}
