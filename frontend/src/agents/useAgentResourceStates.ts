import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { selectToken } from '../preferences/preferenceSlice';
import type { Agent, ResourceState } from './types';

/** The agent as read, and every tool, source and prompt it runs. */
export type AgentResources = { agent: Agent; items: ResourceState[] };

/** The agent's own items, then its workflow nodes' ones it doesn't have. */
export function mergeStates(
  own: ResourceState[],
  nodes: ResourceState[],
): ResourceState[] {
  const seen = new Set(own.map((item) => item.key.toLowerCase()));
  return [...own, ...nodes.filter((item) => !seen.has(item.key.toLowerCase()))];
}

/**
 * Reads an agent and the run state of what it uses: `resource_states` from
 * the agent read, plus the workflow read's for a workflow agent's node
 * tools and sources. Only owners and editors get the states; everyone else
 * gets an empty list.
 *
 * Args:
 *   agentId: The agent to read; nothing is read without one.
 *   reloadKey: Read again when this changes (the agent's saved tools).
 *
 * Returns:
 *   The agent and its items, or null while loading or when the agent
 *   can't be read. A failed workflow read leaves the agent's own items.
 */
export default function useAgentResourceStates(
  agentId: string | undefined,
  reloadKey = '',
): AgentResources | null {
  const token = useSelector(selectToken);
  const [loaded, setLoaded] = useState<AgentResources | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoaded(null);
    if (!agentId) return;
    const load = async () => {
      let agent: Agent;
      try {
        const response = await userService.getAgent(agentId, token);
        if (!response.ok) return;
        agent = await response.json();
      } catch {
        return;
      }
      let items = agent.resource_states ?? [];
      if (agent.agent_type === 'workflow' && agent.workflow) {
        try {
          const response = await userService.getWorkflow(agent.workflow, token);
          if (response.ok) {
            const body = await response.json();
            items = mergeStates(items, body?.data?.resource_states ?? []);
          }
        } catch {
          // The agent's own items still show.
        }
      }
      if (!cancelled) setLoaded({ agent, items });
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [agentId, reloadKey, token]);

  return loaded;
}
