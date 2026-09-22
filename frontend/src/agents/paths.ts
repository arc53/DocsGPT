import type { AgentFilterTab } from './hooks/useAgentSearch';
import type { Agent } from './types';

/**
 * Routes under `/agents` cover two different things: *using* an agent (a
 * conversation) and *managing* them (the list, the editor, logs, schedules).
 * They used to share the `/agents/…` prefix, which left no way to tell them
 * apart from the pathname — so the sidebar could not react to one without
 * also reacting to the other. Management now lives under `/agents/manage`.
 *
 * Every caller builds its links from here rather than from a literal, so the
 * next move costs one edit instead of thirty.
 */

/** Root of the management mode; also the agents section's root path. */
export const AGENTS_MANAGE_ROOT = '/agents/manage';

/** URL segment for each list filter. `all` is the root, so it has none. */
const FILTER_SLUGS: Record<Exclude<AgentFilterTab, 'all'>, string> = {
  template: 'templates',
  user: 'mine',
  team: 'team',
  // Not `shared`: `/agents/shared/:token` already means "open this public
  // agent", and two different meanings under one word invites mistakes.
  shared: 'discovered',
};

const SLUG_FILTERS = Object.fromEntries(
  Object.entries(FILTER_SLUGS).map(([filter, slug]) => [slug, filter]),
) as Record<string, AgentFilterTab>;

export const isWorkflowAgent = (agent: Pick<Agent, 'agent_type'>): boolean =>
  agent.agent_type === 'workflow';

/** The list narrowed to one filter; each filter is its own linkable route. */
export const agentsFilterPath = (filter: AgentFilterTab): string =>
  filter === 'all'
    ? AGENTS_MANAGE_ROOT
    : `${AGENTS_MANAGE_ROOT}/${FILTER_SLUGS[filter]}`;

/**
 * The agent list, optionally scoped to a folder and to a filter. The filter
 * has to be carried explicitly: it lives in the path now, so building a
 * folder URL off the bare root would silently widen the list back to every
 * section the moment someone opened a folder from a filtered view.
 */
export const agentsListPath = (
  folderId?: string | null,
  filter: AgentFilterTab = 'all',
): string => {
  const base = agentsFilterPath(filter);
  return folderId ? `${base}?folder=${encodeURIComponent(folderId)}` : base;
};

/** Which filter a list route selects; `all` for anything unrecognised. */
export const filterFromPath = (pathname: string): AgentFilterTab => {
  const slug = pathname.startsWith(`${AGENTS_MANAGE_ROOT}/`)
    ? pathname.slice(AGENTS_MANAGE_ROOT.length + 1).split('/')[0]
    : '';
  return SLUG_FILTERS[slug] ?? 'all';
};

export const agentNewPath = (
  options: { workflow?: boolean; folderId?: string | null } = {},
): string => {
  const base = options.workflow
    ? `${AGENTS_MANAGE_ROOT}/workflow/new`
    : `${AGENTS_MANAGE_ROOT}/new`;
  return options.folderId
    ? `${base}?folder_id=${encodeURIComponent(options.folderId)}`
    : base;
};

export const agentEditPath = (
  agentId: string | undefined,
  workflow = false,
): string =>
  workflow
    ? `${AGENTS_MANAGE_ROOT}/workflow/edit/${agentId}`
    : `${AGENTS_MANAGE_ROOT}/edit/${agentId}`;

/** Edit path for an agent whose type decides which editor opens. */
export const agentEditPathFor = (
  agent: Pick<Agent, 'id' | 'agent_type'>,
): string => agentEditPath(agent.id, isWorkflowAgent(agent));

export const agentLogsPath = (agentId: string | undefined): string =>
  `${AGENTS_MANAGE_ROOT}/logs/${agentId}`;

export const agentSchedulesPath = (agentId: string | undefined): string =>
  `${AGENTS_MANAGE_ROOT}/schedules/${agentId}`;

/** Using an agent, not managing it — deliberately outside `/agents/manage`. */
export const agentChatPath = (
  agentId: string | undefined,
  conversationId = 'new',
) => `/agents/${agentId}/c/${conversationId}`;

export const sharedAgentPath = (sharedToken: string | undefined): string =>
  `/agents/shared/${sharedToken}`;

export type AgentScopedPage = 'overview' | 'logs' | 'schedules';

const AGENT_SCOPED_ROUTE = new RegExp(
  `^${AGENTS_MANAGE_ROOT}/(?:workflow/)?(edit|logs|schedules)/([^/]+)`,
);

/**
 * Whether a route is scoped to one agent, and which of its pages it is.
 * Drives the per-agent sidebar nav.
 */
export function matchAgentScopedRoute(
  pathname: string,
): { agentId: string; page: AgentScopedPage; workflow: boolean } | null {
  const match = AGENT_SCOPED_ROUTE.exec(pathname);
  if (!match) return null;
  const [, segment, agentId] = match;
  return {
    agentId,
    page: segment === 'edit' ? 'overview' : (segment as AgentScopedPage),
    workflow: pathname.startsWith(`${AGENTS_MANAGE_ROOT}/workflow/`),
  };
}
