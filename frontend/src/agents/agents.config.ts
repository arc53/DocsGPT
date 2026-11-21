import userService from '../api/services/userService';
import {
  selectAgents,
  selectSharedAgents,
  setAgents,
  setSharedAgents,
} from '../preferences/preferenceSlice';

/**
 * The agent list's sections. `user` is the workspace's own agents (My
 * agents in Personal, the team's in a team); `teamShared` the ones other
 * teams shared with the team (a team only); `sharedWithYou` the ones people
 * shared with the caller directly (Personal only); `shared` the public ones
 * opened by a link (Discovered, Personal only).
 */
export type AgentSectionId = 'user' | 'teamShared' | 'sharedWithYou' | 'shared';

export const agentSectionsConfig = [
  {
    id: 'user' as const,
    title: 'My agents',
    description: 'Agents created or published by you',
    showNewAgentButton: true,
    emptyStateDescription: 'You don’t have any created agents yet.',
    fetchAgents: (token: string | null) => userService.getAgents(token),
    selectData: selectAgents,
    updateAction: setAgents,
  },
  {
    // Another team's agents shared with this team: split out of the team's
    // /api/get_agents payload by `origin`, like Shared with you.
    id: 'teamShared' as const,
    title: 'Shared with this team',
    description: 'Agents other teams shared with this team',
    showNewAgentButton: false,
    emptyStateDescription: 'No other team has shared an agent with this team.',
    fetchAgents: (token: string | null) => userService.getAgents(token),
    selectData: selectAgents,
    updateAction: setAgents,
  },
  {
    // Split out of the same /api/get_agents payload by `origin`, so it reuses
    // the user section's selector and action.
    id: 'sharedWithYou' as const,
    title: 'Shared with you',
    description: 'Agents people shared with you',
    showNewAgentButton: false,
    emptyStateDescription: 'No one has shared an agent with you yet.',
    fetchAgents: (token: string | null) => userService.getAgents(token),
    selectData: selectAgents,
    updateAction: setAgents,
  },
  {
    id: 'shared' as const,
    title: 'Discovered',
    description: "Public agents you've opened via a link",
    showNewAgentButton: false,
    emptyStateDescription: "You haven't opened any public agents yet.",
    fetchAgents: (token: string | null) => userService.getSharedAgents(token),
    selectData: selectSharedAgents,
    updateAction: setSharedAgents,
  },
];

/**
 * The sections a team workspace leaves out: people share with a person, and
 * a public link is opened by one.
 */
export const PERSONAL_ONLY_SECTIONS: readonly AgentSectionId[] = [
  'sharedWithYou',
  'shared',
];

/** The sections Personal leaves out: other teams share with a team. */
export const TEAM_ONLY_SECTIONS: readonly AgentSectionId[] = ['teamShared'];
