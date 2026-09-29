import { type ReactNode, useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { Navigate, useParams } from 'react-router-dom';

import userService from '../api/services/userService';
import { LoadingState } from '../components/ui/loading-state';
import {
  selectAgents,
  selectSelectedAgent,
  selectSharedAgents,
  selectToken,
} from '../preferences/preferenceSlice';
import { canAgent } from './agentAccess';
import { agentsListPath } from './paths';
import type { Agent } from './types';

type AgentRouteGuardProps = {
  /** The action the page needs (`view`, `view_logs`, `manage_schedules`). */
  action: string;
  children: ReactNode;
};

/**
 * Opens an agent's page only for a role that may use it.
 *
 * Decides from the agent already in the store when that record carries the
 * server's `allowed_actions`, else fetches the agent. Nothing of the page
 * renders until it knows (a loading ring stands in), so a viewer never sees
 * a flash of the edit form.
 * A caller who may not open the page, or an agent that does not load, goes
 * back to the agent list.
 *
 * @param action The agent action the wrapped page needs.
 * @param children The page.
 */
export default function AgentRouteGuard({
  action,
  children,
}: AgentRouteGuardProps) {
  const { agentId } = useParams();
  const token = useSelector(selectToken);
  const agents = useSelector(selectAgents);
  const sharedAgents = useSelector(selectSharedAgents);
  const selectedAgent = useSelector(selectSelectedAgent);

  const stored = [
    ...(agents ?? []),
    ...(sharedAgents ?? []),
    ...(selectedAgent ? [selectedAgent] : []),
  ].find((agent) => agent.id === agentId && agent.allowed_actions);

  const [fetched, setFetched] = useState<{
    id: string;
    agent: Agent | null;
  } | null>(null);

  const needsFetch = Boolean(agentId) && !stored;
  useEffect(() => {
    if (!needsFetch || !agentId) return;
    let cancelled = false;
    userService
      .getAgent(agentId, token)
      .then(async (response: Response) => {
        const agent = response.ok ? ((await response.json()) as Agent) : null;
        if (!cancelled) setFetched({ id: agentId, agent });
      })
      .catch(() => {
        if (!cancelled) setFetched({ id: agentId, agent: null });
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, needsFetch, token]);

  if (!agentId) return <>{children}</>;

  let agent: Agent | null | undefined = stored;
  if (!agent) {
    if (fetched?.id !== agentId) return <LoadingState fill="parent" />;
    agent = fetched.agent;
  }
  if (!agent || !canAgent(agent, action))
    return <Navigate to={agentsListPath()} replace />;
  return <>{children}</>;
}
