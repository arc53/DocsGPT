import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react';
import { useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { selectToken } from '../../preferences/preferenceSlice';
import type { Agent } from '../types';

/**
 * The agent record `AgentRouteGuard` fetched to let the page open, so the
 * page doesn't read it a second time; null when the guard decided from the
 * agent list (whose records may lack the config) or fetched nothing.
 */
export const GuardedAgentContext = createContext<Agent | null>(null);

type AgentState = { id?: string; agent?: Agent; error: boolean };

/**
 * The agent an agent page shows, read once (GET /api/get_agent), or taken
 * from the route guard that has just read it.
 *
 * Args:
 *   agentId: The agent's id from the route.
 *
 * Returns:
 *   `agent` once read (the last one stays while `reload` reads it again),
 *   `error` when the read failed (DESIGN › Load errors), `reload`, and
 *   `setAgent` to show a change before the server's copy comes back.
 */
export function useAgent(agentId: string | undefined) {
  const token = useSelector(selectToken);
  const guarded = useContext(GuardedAgentContext);
  const seed = guarded && guarded.id === agentId ? guarded : undefined;
  const [state, setState] = useState<AgentState>({ error: false });
  const [reloadKey, setReloadKey] = useState(0);
  // Read only once asked to reload when the guard handed the record over.
  const useSeed = Boolean(seed) && reloadKey === 0;

  useEffect(() => {
    if (!agentId || useSeed) return;
    let cancelled = false;
    setState((prev) =>
      prev.id === agentId ? { ...prev, error: false } : { error: false },
    );
    userService
      .getAgent(agentId, token)
      .then((response) => {
        if (!response.ok) throw new Error('agent');
        return response.json();
      })
      .then((record: Agent) => {
        if (!cancelled) setState({ id: agentId, agent: record, error: false });
      })
      .catch(() => {
        if (cancelled) return;
        setState((prev) => ({
          id: agentId,
          agent: prev.id === agentId ? prev.agent : undefined,
          error: true,
        }));
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, token, reloadKey, useSeed]);

  const current = state.id === agentId ? state : undefined;
  // The guard's record until this hook has read one of its own.
  const agent = current?.agent ?? seed;
  const reload = useCallback(() => setReloadKey((key) => key + 1), []);
  const setAgent = useCallback(
    (update: (prev: Agent) => Agent) =>
      setState((prev) => {
        const base = (prev.id === agentId ? prev.agent : undefined) ?? seed;
        return base ? { id: agentId, agent: update(base), error: false } : prev;
      }),
    [agentId, seed],
  );
  return { agent, error: current?.error ?? false, reload, setAgent };
}
