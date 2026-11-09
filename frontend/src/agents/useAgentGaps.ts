import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import { type AgentGaps, getAgentGaps } from '../drafter/drafterApi';
import { selectToken } from '../preferences/preferenceSlice';

/**
 * An agent's gap summary for the improve drawer's first screen, read each
 * time `active` turns on (the drawer opens), so a reopened drawer catches up
 * with the sweep. The last answer stays on screen while the next one loads;
 * null until the first one lands, and for another agent's id.
 *
 * Args:
 *   agentId: The saved agent, or null for a new one (nothing is read).
 *   active: Read now: the drawer is open in improve mode for a caller who
 *     may edit the agent.
 *
 * Returns:
 *   The summary, or null while unknown.
 */
export function useAgentGaps(
  agentId: string | null,
  active: boolean,
): AgentGaps | null {
  const token = useSelector(selectToken);
  const [state, setState] = useState<{ id: string; gaps: AgentGaps } | null>(
    null,
  );

  useEffect(() => {
    if (!agentId || !active) return;
    const controller = new AbortController();
    void getAgentGaps(agentId, token, controller.signal).then((gaps) => {
      if (!controller.signal.aborted) setState({ id: agentId, gaps });
    });
    return () => controller.abort();
  }, [agentId, active, token]);

  return state && state.id === agentId ? state.gaps : null;
}
