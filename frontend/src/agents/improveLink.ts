import { useContext } from 'react';
import { useSelector } from 'react-redux';

import {
  selectAgents,
  selectSelectedAgent,
  selectSharedAgents,
} from '../preferences/preferenceSlice';
import { OPTION_KEYS } from '../settings/insights/format';
import { can } from '../utils/accessUtils';
import { GuardedAgentContext } from './hooks/useAgent';
import { agentEditPath, isWorkflowAgent } from './paths';
import type { Agent } from './types';

/** How the Docs gaps panel grouped the row a gap hand-off came from. */
export type GapGroup = 'page' | 'source' | 'topic';
const GAP_GROUPS: readonly GapGroup[] = ['page', 'source', 'topic'];

/**
 * What the agent form's drawer starts on when opened from Insights or Logs:
 * a gap (the Docs gaps panel) or one conversation (a Logs row). `where` is
 * the panel's name for the gap's group (a page, a source or a topic), which
 * only titles the gap's card: a link's text never words the message the
 * drawer sends. A Page or Source row also carries `group_key`, the
 * row's key as the server groups by it (null for the row of answers with
 * no source), which the drafter reads that row's questions by.
 */
export type ImproveHandoff =
  | {
      kind: 'gap';
      gap_type: string;
      topic: string | null;
      where: string;
      group_by: GapGroup;
      group_key: string | null;
    }
  | { kind: 'conversation'; conversation_id: string };

/** The query keys a hand-off uses; the form drops them once it has read them. */
export const IMPROVE_PARAMS = [
  'improve',
  'gap_type',
  'topic',
  'where',
  'group_by',
  'group_key',
  'conversation',
] as const;

/** A conversation id as the server takes it. */
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
/** Longest gap type and names a link carries (a topic name is at most 60). */
const GAP_TYPE_MAX = 64;
const NAME_MAX = 300;
/** Longest row key a link carries (a page's URL), as the server cuts it. */
const GROUP_KEY_MAX = 500;

/**
 * The agent form with its drawer opening in improve mode on `handoff`.
 *
 * Args:
 *   agentId: The agent to improve.
 *   handoff: The gap or conversation it starts from.
 *
 * Returns:
 *   The edit path with the hand-off in its query.
 */
export function agentImprovePath(
  agentId: string,
  handoff: ImproveHandoff,
): string {
  const params = new URLSearchParams({ improve: handoff.kind });
  if (handoff.kind === 'gap') {
    params.set('gap_type', handoff.gap_type);
    if (handoff.topic) params.set('topic', handoff.topic);
    params.set('where', handoff.where);
    params.set('group_by', handoff.group_by);
    if (handoff.group_key) params.set('group_key', handoff.group_key);
  } else params.set('conversation', handoff.conversation_id);
  return `${agentEditPath(agentId)}?${params.toString()}`;
}

/**
 * The hand-off in the agent form's query, if it carries a valid one.
 *
 * Args:
 *   params: The form's search params.
 *
 * Returns:
 *   The hand-off, or null without one (or with a malformed one).
 */
export function readImproveHandoff(
  params: URLSearchParams,
): ImproveHandoff | null {
  const kind = params.get('improve');
  if (kind === 'conversation') {
    const id = params.get('conversation') ?? '';
    return UUID_RE.test(id) ? { kind, conversation_id: id } : null;
  }
  if (kind !== 'gap') return null;
  const gapType = params.get('gap_type')?.trim() ?? '';
  const where = params.get('where')?.trim() ?? '';
  const topic = params.get('topic')?.trim() || null;
  // A link from before the grouping went with it is a topic's.
  const groupBy = (params.get('group_by') ?? 'topic') as GapGroup;
  const groupKey = params.get('group_key')?.trim() || null;
  if (!gapType || gapType.length > GAP_TYPE_MAX || !where) return null;
  // One of the types Insights labels with: the message is worded from it.
  if (!Object.hasOwn(OPTION_KEYS.gap_type, gapType)) return null;
  if (where.length > NAME_MAX || (topic && topic.length > NAME_MAX))
    return null;
  if (!GAP_GROUPS.includes(groupBy)) return null;
  if (groupKey && groupKey.length > GROUP_KEY_MAX) return null;
  return {
    kind,
    gap_type: gapType,
    topic,
    where,
    group_by: groupBy,
    group_key: groupBy === 'topic' ? null : groupKey,
  };
}

/**
 * Whether a caller may improve the agent with the drawer: its record
 * carries the server's access fields and allows `edit`, and it opens in the
 * classic form (a workflow agent has its own editor).
 */
export function canImproveAgent(agent: Agent | null | undefined): boolean {
  return (
    !!agent?.id &&
    !!agent.allowed_actions &&
    can(agent, 'edit') &&
    !isWorkflowAgent(agent)
  );
}

/**
 * Find an agent the page already holds, with its access fields, without a
 * request: the record the route guard read, or the store's lists (the
 * caller's own and shared agents, the selected one).
 *
 * Returns:
 *   A lookup by id; null for an agent the page doesn't hold.
 */
export function useKnownAgent(): (id: string | undefined) => Agent | null {
  const guarded = useContext(GuardedAgentContext);
  const agents = useSelector(selectAgents);
  const shared = useSelector(selectSharedAgents);
  const selected = useSelector(selectSelectedAgent);
  return (id) =>
    id
      ? ([guarded, ...(agents ?? []), ...(shared ?? []), selected].find(
          (agent): agent is Agent =>
            !!agent && agent.id === id && !!agent.allowed_actions,
        ) ?? null)
      : null;
}
