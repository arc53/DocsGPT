import { useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { selectToken } from '../../preferences/preferenceSlice';
import type { Agent } from '../types';
import {
  approvalGatedTools,
  type AgentToolSummary,
  type ApprovalTool,
  type ApprovalToolInfo,
} from './toolApproval';

export type ScheduleAgentContext = {
  agent: Agent | undefined;
  /** True while the agent record loads. */
  loadingAgent: boolean;
  /** The agent's tools a schedule has to pre-approve (see toolApproval). */
  approvalTools: ApprovalTool[];
  /**
   * True once the agent and the caller's tools have both loaded (or failed),
   * so `approvalTools` is final. The schedule form reads it once, when it
   * mounts, so an edit must not open before this.
   */
  ready: boolean;
};

/**
 * What the schedule form needs to know about an agent: the record and which
 * of its tools need pre-approval. `null` (an agentless schedule, or no agent
 * picked yet) yields no agent and no tools, ready at once.
 *
 * Args:
 *   agentId: The agent whose schedules are being created or edited.
 *
 * Returns:
 *   The agent, its approval-gated tools and whether both have loaded.
 */
export default function useScheduleAgentContext(
  agentId: string | null | undefined,
): ScheduleAgentContext {
  const token = useSelector(selectToken);
  const [agent, setAgent] = useState<Agent | undefined>();
  const [loadedAgentId, setLoadedAgentId] = useState<string | null>(null);
  // The caller's tools with their actions, to tell which of the agent's
  // tools need approval. A failed read lists every tool as needing it.
  const [userTools, setUserTools] = useState<ApprovalToolInfo[] | null>(null);

  useEffect(() => {
    if (!agentId) {
      setAgent(undefined);
      setLoadedAgentId(null);
      return;
    }
    let cancelled = false;
    setLoadedAgentId(null);
    userService
      .getAgent(agentId, token)
      .then((response: Response) => {
        if (!response.ok) throw new Error('Failed to fetch agent');
        return response.json();
      })
      .then((data: Agent) => {
        if (!cancelled) setAgent(data);
      })
      .catch((error: unknown) => {
        console.error(error);
        if (!cancelled) setAgent(undefined);
      })
      .finally(() => {
        if (!cancelled) setLoadedAgentId(agentId);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, token]);

  useEffect(() => {
    let cancelled = false;
    userService
      .getUserTools(token)
      .then((response: Response) => (response.ok ? response.json() : null))
      .then((data: { tools?: ApprovalToolInfo[] } | null) => {
        if (!cancelled) setUserTools(data?.tools ?? []);
      })
      .catch(() => {
        if (!cancelled) setUserTools([]);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const currentAgent = agentId && loadedAgentId === agentId ? agent : undefined;

  const approvalTools = useMemo(() => {
    if (!currentAgent) return [];
    const details: AgentToolSummary[] = currentAgent.tool_details?.length
      ? currentAgent.tool_details
      : (currentAgent.tools ?? []).map((id) => ({ id, name: id }));
    return approvalGatedTools(details, userTools ?? []);
  }, [currentAgent, userTools]);

  const loadingAgent = Boolean(agentId) && loadedAgentId !== agentId;
  return {
    agent: currentAgent,
    loadingAgent,
    approvalTools,
    ready: !agentId || (!loadingAgent && userTools !== null),
  };
}
