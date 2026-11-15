import { AGENTS_MANAGE_ROOT } from '../agents/paths';

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
