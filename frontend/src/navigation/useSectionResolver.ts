import { useCallback } from 'react';
import { useSelector } from 'react-redux';

import { matchAgentScopedRoute } from '../agents/paths';
import {
  selectAgents,
  selectSelectedAgent,
  selectSharedAgents,
} from '../preferences/preferenceSlice';
import { buildAgentSection, getSectionForPath, type Section } from './sections';

/**
 * Resolves any pathname to its section, including the ones built per route
 * from a record in the store. Taking a pathname rather than reading the
 * current one lets the sidebar resolve a route it is *about* to go to, which
 * is what allows it to start moving on the click.
 */
export function useSectionResolver(): (pathname: string) => Section | null {
  const agents = useSelector(selectAgents);
  const sharedAgents = useSelector(selectSharedAgents);
  const selectedAgent = useSelector(selectSelectedAgent);

  return useCallback(
    (pathname: string) => {
      const scoped = matchAgentScopedRoute(pathname);
      if (!scoped) return getSectionForPath(pathname);

      const name = [
        ...(agents ?? []),
        ...(sharedAgents ?? []),
        ...(selectedAgent ? [selectedAgent] : []),
      ].find((agent) => agent.id === scoped.agentId)?.name;

      return buildAgentSection(scoped.agentId, name, scoped.workflow);
    },
    [agents, sharedAgents, selectedAgent],
  );
}
