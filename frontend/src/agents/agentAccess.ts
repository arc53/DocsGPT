import { can, type AccessFields } from '../utils/accessUtils';
import type { Agent } from './types';

/**
 * Whether the chat header and the phone top bar offer Edit for an agent.
 *
 * Prefers the agent list's copy, which carries the server's access fields.
 * An agent that is not in the list (a template, a link-shared agent) must
 * carry `allowed_actions` itself; without them it gets no Edit, so a record
 * with no access fields is never taken for the caller's own.
 *
 * @param agent The agent the chat is with.
 * @param agents The caller's agent list (own and team-shared).
 * @returns True when the role may open the agent's edit page.
 */
export function canOpenAgentEditor(
  agent: Agent | null | undefined,
  agents?: Agent[] | null,
): boolean {
  if (!agent?.id) return false;
  const listed = agents?.find((a) => a.id === agent.id);
  if (listed) return can(listed, 'view');
  return Boolean(agent.allowed_actions) && can(agent, 'view');
}

/** Actions that only make sense once an agent is published. */
const PUBLISHED_ONLY = new Set(['view_logs', 'manage_schedules', 'pin']);

/**
 * `can()` for an agent, minus what a draft can't have: a draft has no runs
 * to log, no schedule that fires and nothing to pin, so Logs, Schedules and
 * Pin wait until it's published. An agent without a status (a record still
 * loading) is treated as published.
 *
 * @param agent The agent, with its access fields and status.
 * @param action The agent action to check.
 * @returns True when the role allows it and the agent's state makes sense.
 */
export function canAgent(
  agent: (AccessFields & { status?: string }) | null | undefined,
  action: string,
): boolean {
  if (!agent) return false;
  if (
    PUBLISHED_ONLY.has(action) &&
    agent.status &&
    agent.status !== 'published'
  )
    return false;
  return can(agent, action);
}
