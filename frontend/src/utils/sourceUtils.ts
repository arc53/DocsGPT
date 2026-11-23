import type { Doc } from '../models/misc';

/** Stable picker id for a source: its id, or its date for legacy rows without one. */
export function sourceItemId(doc: Pick<Doc, 'id' | 'date'>): string {
  return doc.id || doc.date;
}

export type AgentSourcePayload = { source: string; sources: string[] };

/**
 * Serialise a picker selection into the agent payload: one selection goes in
 * the legacy single ``source`` field, several go in ``sources``, and none
 * leaves both empty (the agent then skips retrieval). Picker ids resolve to
 * source ids; ids not in ``docs`` (e.g. an owner's source a team editor can't
 * list) pass through unchanged.
 */
export function serializeAgentSources(
  selectedIds: Iterable<string>,
  docs: Doc[] | null | undefined,
): AgentSourcePayload {
  const ids = Array.from(new Set(selectedIds))
    .map((id) => docs?.find((doc) => sourceItemId(doc) === id)?.id ?? id)
    .filter(Boolean);
  if (ids.length > 1) return { source: '', sources: ids };
  if (ids.length === 1) return { source: ids[0], sources: [] };
  return { source: '', sources: [] };
}

/**
 * Selected source ids for a stored agent: the legacy single ``source`` and the
 * ``sources`` list merged, because retrieval reads both. Preferring one over
 * the other would drop the omitted field on the next save. The legacy
 * ``"default"`` placeholder means no source.
 */
export function selectedSourceIdsFromAgent(agent: {
  source?: string;
  sources?: string[];
}): string[] {
  const ids = [
    ...(agent.source ? [agent.source] : []),
    ...(agent.sources ?? []),
  ];
  return Array.from(new Set(ids)).filter(
    (id) => Boolean(id) && id !== 'default',
  );
}
