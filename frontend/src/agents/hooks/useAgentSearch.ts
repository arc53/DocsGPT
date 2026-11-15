import { useCallback, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';

import {
  selectAgents,
  selectSharedAgents,
  selectTemplateAgents,
} from '../../preferences/preferenceSlice';
import { splitByOrigin } from '../../workspace/itemOrigin';
import { AgentSectionId } from '../agents.config';
import { Agent } from '../types';

/**
 * A list filter: All, one section, or `team`, the old Team section's
 * address (read as Shared with you in Personal, the team's agents in a team).
 */
export type AgentFilterTab = 'all' | AgentSectionId | 'team';

export type AgentsBySection = Record<AgentSectionId, Agent[]>;

interface UseAgentSearchResult {
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  filteredAgentsBySection: AgentsBySection;
  totalAgentsBySection: Record<AgentSectionId, number>;
  hasAnyAgents: boolean;
  hasFilteredResults: boolean;
  isDataLoaded: Record<AgentSectionId, boolean>;
}

export const filterAgentsByQuery = (
  agents: Agent[] | null,
  query: string,
): Agent[] => {
  if (!agents) return [];
  if (!query.trim()) return agents;

  const normalizedQuery = query.toLowerCase().trim();
  return agents.filter(
    (agent) =>
      agent.name.toLowerCase().includes(normalizedQuery) ||
      agent.description?.toLowerCase().includes(normalizedQuery),
  );
};

/**
 * Search and filtering for the agent list. The filter is passed in rather
 * than held here: it lives in the route, so it stays linkable and survives a
 * reload.
 */
export function useAgentSearch(
  activeFilter: AgentFilterTab = 'all',
): UseAgentSearchResult {
  const [searchQuery, setSearchQuery] = useState('');

  const templateAgents = useSelector(selectTemplateAgents);
  const allUserAgents = useSelector(selectAgents);
  const sharedAgents = useSelector(selectSharedAgents);

  // /api/get_agents lists the workspace's own agents (the caller's in
  // Personal, the team's in a team) and, in Personal, the ones shared with
  // the caller. Split them by `origin`, keeping the null (still-loading)
  // state for both.
  const split = useMemo(
    () => (allUserAgents === null ? null : splitByOrigin(allUserAgents)),
    [allUserAgents],
  );
  const userAgents = useMemo(
    () => (split === null ? null : [...split.own, ...split.team]),
    [split],
  );
  const sharedWithYouAgents = split === null ? null : split.shared;

  const handleSearchChange = useCallback((query: string) => {
    setSearchQuery(query);
  }, []);

  const isDataLoaded = useMemo(
    (): Record<AgentSectionId, boolean> => ({
      template: templateAgents !== null,
      user: userAgents !== null,
      sharedWithYou: sharedWithYouAgents !== null,
      shared: sharedAgents !== null,
    }),
    [templateAgents, userAgents, sharedWithYouAgents, sharedAgents],
  );

  const totalAgentsBySection = useMemo(
    (): Record<AgentSectionId, number> => ({
      template: templateAgents?.length ?? 0,
      user: userAgents?.length ?? 0,
      sharedWithYou: sharedWithYouAgents?.length ?? 0,
      shared: sharedAgents?.length ?? 0,
    }),
    [templateAgents, userAgents, sharedWithYouAgents, sharedAgents],
  );

  const filteredAgentsBySection = useMemo((): AgentsBySection => {
    const filtered = {
      template: filterAgentsByQuery(templateAgents, searchQuery),
      user: filterAgentsByQuery(userAgents, searchQuery),
      sharedWithYou: filterAgentsByQuery(sharedWithYouAgents, searchQuery),
      shared: filterAgentsByQuery(sharedAgents, searchQuery),
    };

    if (activeFilter === 'all') {
      return filtered;
    }

    return {
      template: activeFilter === 'template' ? filtered.template : [],
      user: activeFilter === 'user' ? filtered.user : [],
      sharedWithYou:
        activeFilter === 'sharedWithYou' ? filtered.sharedWithYou : [],
      shared: activeFilter === 'shared' ? filtered.shared : [],
    };
  }, [
    templateAgents,
    userAgents,
    sharedWithYouAgents,
    sharedAgents,
    searchQuery,
    activeFilter,
  ]);

  const hasAnyAgents = useMemo(() => {
    return (
      totalAgentsBySection.template > 0 ||
      totalAgentsBySection.user > 0 ||
      totalAgentsBySection.sharedWithYou > 0 ||
      totalAgentsBySection.shared > 0
    );
  }, [totalAgentsBySection]);

  const hasFilteredResults = useMemo(() => {
    return (
      filteredAgentsBySection.template.length > 0 ||
      filteredAgentsBySection.user.length > 0 ||
      filteredAgentsBySection.sharedWithYou.length > 0 ||
      filteredAgentsBySection.shared.length > 0
    );
  }, [filteredAgentsBySection]);

  return {
    searchQuery,
    setSearchQuery: handleSearchChange,
    filteredAgentsBySection,
    totalAgentsBySection,
    hasAnyAgents,
    hasFilteredResults,
    isDataLoaded,
  };
}
