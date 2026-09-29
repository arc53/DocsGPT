import type { Node } from 'reactflow';

import type { ResourceState } from '../types';

/** Tool and source ids a workflow's agent nodes reference, lowercased. */
export type NodeResourceIds = { tool: Set<string>; source: Set<string> };

const KEYS = { tool: 'tools', source: 'sources' } as const;

function idsOf(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String);
  return value ? [String(value)] : [];
}

/**
 * The tool and source ids the agent nodes reference now.
 *
 * Args:
 *   nodes: The canvas nodes (an agent node keeps them in `data.config`).
 */
export function nodeResourceIds(nodes: Node[]): NodeResourceIds {
  const ids: NodeResourceIds = { tool: new Set(), source: new Set() };
  for (const node of nodes) {
    if (node.type !== 'agent') continue;
    const config = (node.data?.config ?? {}) as Record<string, unknown>;
    for (const type of ['tool', 'source'] as const)
      idsOf(config[KEYS[type]]).forEach((id) =>
        ids[type].add(id.toLowerCase()),
      );
  }
  return ids;
}

/**
 * Stopped node resources still on the canvas, so one removed here (not yet
 * saved) leaves the notice.
 *
 * Args:
 *   states: `resource_states` from the workflow read.
 *   ids: What the nodes reference now.
 */
export function stoppedNodeResources(
  states: ResourceState[],
  ids: NodeResourceIds,
): ResourceState[] {
  return states.filter(
    (item) =>
      item.state === 'stopped' &&
      item.type !== 'prompt' &&
      ids[item.type].has(item.id.toLowerCase()),
  );
}

/**
 * The nodes with one tool or source taken off every agent node.
 *
 * Args:
 *   nodes: The canvas nodes.
 *   item: The tool or source to take off.
 */
export function withoutNodeResource(
  nodes: Node[],
  item: Pick<ResourceState, 'type' | 'id'>,
): Node[] {
  if (item.type === 'prompt') return nodes;
  const key = KEYS[item.type];
  const id = item.id.toLowerCase();
  return nodes.map((node) => {
    const config = node.data?.config;
    if (node.type !== 'agent' || !config || config[key] === undefined)
      return node;
    const kept = idsOf(config[key]).filter((ref) => ref.toLowerCase() !== id);
    if (kept.length === idsOf(config[key]).length) return node;
    return {
      ...node,
      data: {
        ...node.data,
        config: {
          ...config,
          [key]: Array.isArray(config[key]) ? kept : (kept[0] ?? ''),
        },
      },
    };
  });
}
