import { useMemo } from 'react';
import { useSelector } from 'react-redux';
import { useLocation } from 'react-router-dom';

import { matchAgentScopedRoute } from '../agents/paths';
import {
  selectAgents,
  selectSelectedAgent,
  selectSharedAgents,
} from '../preferences/preferenceSlice';
import {
  buildAgentSection,
  getActiveItem,
  getSectionForPath,
  type Section,
  type SectionItem,
} from './sections';

/**
 * The section the current route belongs to, and the nav item within it.
 *
 * Most sections are static and come straight from the registry. A route
 * scoped to one agent gets a section built on the spot, since its title is
 * the agent's name — which lives in the store, not in the path.
 */
export function useSectionContext(): {
  section: Section | null;
  item: SectionItem | null;
} {
  const { pathname } = useLocation();
  const agents = useSelector(selectAgents);
  const sharedAgents = useSelector(selectSharedAgents);
  const selectedAgent = useSelector(selectSelectedAgent);

  const section = useMemo(() => {
    const scoped = matchAgentScopedRoute(pathname);
    if (!scoped) return getSectionForPath(pathname);

    const name = [
      ...(agents ?? []),
      ...(sharedAgents ?? []),
      ...(selectedAgent ? [selectedAgent] : []),
    ].find((agent) => agent.id === scoped.agentId)?.name;

    // An agent saved moments ago may not be in the store yet; the section
    // falls back to a generic title until it arrives.
    return buildAgentSection(scoped.agentId, name, scoped.workflow);
  }, [pathname, agents, sharedAgents, selectedAgent]);

  return {
    section,
    item: section ? getActiveItem(section, pathname) : null,
  };
}
