import { useCallback, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';

import {
  selectAgents,
  selectSharedAgents,
  selectTemplateAgents,
} from '../../preferences/preferenceSlice';
import { AgentSectionId } from '../agents.config';
import { Agent } from '../types';

export type AgentFilterTab = 'all' | AgentSectionId;

export type AgentsBySection = Record<AgentSectionId, Agent[]>;

interface UseAgentSearchResult {
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  activeFilter: AgentFilterTab;
  setActiveFilter: (filter: AgentFilterTab) => void;
  filteredAgentsBySection: AgentsBySection;
  totalAgentsBySection: Record<AgentSectionId, number>;
  hasAnyAgents: boolean;
  hasFilteredResults: boolean;
  isDataLoaded: Record<AgentSectionId, boolean>;
}

const filterAgentsByQuery = (
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

export function useAgentSearch(): UseAgentSearchResult {
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState<AgentFilterTab>('all');

  const templateAgents = useSelector(selectTemplateAgents);
  const allUserAgents = useSelector(selectAgents);
  const sharedAgents = useSelector(selectSharedAgents);

  // /api/get_agents returns both the caller's own agents and agents shared
  // with their teams (tagged ownership:'team'). Split them so "By me" shows
  // only owned agents and "Shared with my team" gets its own section.
  // Preserve the null (still-loading) state for both buckets.
  const userAgents = useMemo(
    () =>
      allUserAgents === null
        ? null
        : allUserAgents.filter((a) => a.ownership !== 'team'),
    [allUserAgents],
  );
  const teamAgents = useMemo(
    () =>
      allUserAgents === null
        ? null
        : allUserAgents.filter((a) => a.ownership === 'team'),
    [allUserAgents],
  );

  const handleSearchChange = useCallback((query: string) => {
    setSearchQuery(query);
  }, []);

  const handleFilterChange = useCallback((filter: AgentFilterTab) => {
    setActiveFilter(filter);
  }, []);

  const isDataLoaded = useMemo(
    (): Record<AgentSectionId, boolean> => ({
      template: templateAgents !== null,
      user: userAgents !== null,
      team: teamAgents !== null,
      shared: sharedAgents !== null,
    }),
    [templateAgents, userAgents, teamAgents, sharedAgents],
  );

  const totalAgentsBySection = useMemo(
    (): Record<AgentSectionId, number> => ({
      template: templateAgents?.length ?? 0,
      user: userAgents?.length ?? 0,
      team: teamAgents?.length ?? 0,
      shared: sharedAgents?.length ?? 0,
    }),
    [templateAgents, userAgents, teamAgents, sharedAgents],
  );

  const filteredAgentsBySection = useMemo((): AgentsBySection => {
    const filtered = {
      template: filterAgentsByQuery(templateAgents, searchQuery),
      user: filterAgentsByQuery(userAgents, searchQuery),
      team: filterAgentsByQuery(teamAgents, searchQuery),
      shared: filterAgentsByQuery(sharedAgents, searchQuery),
    };

    if (activeFilter === 'all') {
      return filtered;
    }

    return {
      template: activeFilter === 'template' ? filtered.template : [],
      user: activeFilter === 'user' ? filtered.user : [],
      team: activeFilter === 'team' ? filtered.team : [],
      shared: activeFilter === 'shared' ? filtered.shared : [],
    };
  }, [
    templateAgents,
    userAgents,
    teamAgents,
    sharedAgents,
    searchQuery,
    activeFilter,
  ]);

  const hasAnyAgents = useMemo(() => {
    return (
      totalAgentsBySection.template > 0 ||
      totalAgentsBySection.user > 0 ||
      totalAgentsBySection.team > 0 ||
      totalAgentsBySection.shared > 0
    );
  }, [totalAgentsBySection]);

  const hasFilteredResults = useMemo(() => {
    return (
      filteredAgentsBySection.template.length > 0 ||
      filteredAgentsBySection.user.length > 0 ||
      filteredAgentsBySection.team.length > 0 ||
      filteredAgentsBySection.shared.length > 0
    );
  }, [filteredAgentsBySection]);

  return {
    searchQuery,
    setSearchQuery: handleSearchChange,
    activeFilter,
    setActiveFilter: handleFilterChange,
    filteredAgentsBySection,
    totalAgentsBySection,
    hasAnyAgents,
    hasFilteredResults,
    isDataLoaded,
  };
}
