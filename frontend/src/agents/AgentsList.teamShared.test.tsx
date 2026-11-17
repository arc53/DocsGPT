import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

import type { WorkspaceState } from '../workspace/workspaceSlice';
import type { Agent } from './types';

const PERSONAL = { id: 'personal', kind: 'personal', name: 'Personal' };
const TEAM = {
  id: 't1',
  kind: 'team',
  name: 'Operations',
  role: 'editor',
  member_count: 12,
};

const state = vi.hoisted(() => ({
  preference: {
    token: null,
    selectedAgent: null,
    agents: [] as unknown[],
    templateAgents: [] as unknown[],
    sharedAgents: [] as unknown[],
  },
  folders: {
    tree: {
      items: [] as unknown[],
      loaded: true,
      loading: false,
      failed: false,
      latestRequestId: null,
      removedParents: {},
    },
  },
  workspace: {} as WorkspaceState,
}));
const moveCalls = vi.hoisted(() => [] as string[]);

vi.mock('react-redux', () => ({
  // A fresh root each read, as a store gives after a change: memoized
  // selectors would otherwise keep the first workspace's answer.
  useSelector: (selector: (s: unknown) => unknown) => selector({ ...state }),
  useDispatch: () => (action: unknown) => Promise.resolve(action),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('./hooks/useAgentsFetch', () => ({
  useAgentsFetch: () => ({
    isLoading: {
      template: false,
      user: false,
      sharedWithYou: false,
      teamShared: false,
      shared: false,
    },
    refetchFolders: async () => undefined,
    refetchUserAgents: async () => undefined,
  }),
}));
vi.mock('../navigation/SectionShell', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../navigation/SectionPills', () => ({ default: () => null }));
vi.mock('../components/PageToolbar', () => ({ default: () => null }));
vi.mock('../modals/ImportAgentModal', () => ({ default: () => null }));
vi.mock('./components/AgentTypeModal', () => ({ default: () => null }));
vi.mock('../navigation/SidebarLevelProvider', () => ({
  useSidebarLevel: () => ({ goToLevel: () => undefined }),
}));
vi.mock('../teams/ShareToTeamModal', () => ({ default: () => null }));
vi.mock('../workspace/move/useMoveToWorkspace', () => ({
  default: (kind: string) => {
    moveCalls.push(kind);
    return { menuOption: () => null, dialog: null };
  },
  useMoveToWorkspace: (kind: string) => {
    moveCalls.push(kind);
    return { menuOption: () => null, dialog: null };
  },
}));

import AgentsList from './AgentsList';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const inWorkspace = (current: 'personal' | 't1', role = 'editor') => {
  state.workspace = {
    current,
    workspaces: [PERSONAL, { ...TEAM, role }],
    loaded: true,
    loading: false,
    epoch: 0,
    lastReason: null,
    latestRequestId: null,
  } as WorkspaceState;
};

const agent = (name: string, fields: Partial<Agent> = {}): Agent =>
  ({
    id: name,
    name,
    description: '',
    status: 'published',
    ...fields,
  }) as Agent;

const own = agent('Mine', {
  origin: 'own',
  access: 'owner',
  workspace: { kind: 'personal', team_id: null },
  created_by: { user_id: 'me', label: 'Me' },
});
const teamAgent = agent('Ops bot', {
  origin: 'team',
  access: 'editor',
  allowed_actions: ['use', 'pin', 'view', 'edit'],
  workspace: { kind: 'team', team_id: 't1' },
  created_by: { user_id: 'dana', label: 'Dana' },
});

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  moveCalls.length = 0;
  state.preference.agents = [];
  state.preference.templateAgents = [];
  state.preference.sharedAgents = [];
  state.folders.tree.items = [];
  inWorkspace('personal');
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

const render = async (path = '/agents/manage') => {
  await act(async () =>
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <AgentsList />
      </MemoryRouter>,
    ),
  );
};

const sectionIds = () =>
  Array.from(
    container.querySelectorAll<HTMLElement>('[data-agent-section]'),
  ).map((el) => el.dataset.agentSection);
const section = (id: string) =>
  container.querySelector<HTMLElement>(`[data-agent-section="${id}"]`);
const titlesIn = (el: HTMLElement | null) =>
  Array.from(el?.querySelectorAll('[data-slot="card-title"]') ?? []).map(
    (title) => title.textContent,
  );
const card = (name: string) =>
  Array.from(
    container.querySelectorAll<HTMLElement>('[data-slot="card"]'),
  ).find(
    (el) => el.querySelector('[data-slot="card-title"]')?.textContent === name,
  );

// Another team's agent shared with this team (Operations shares with Dev).
const received = agent('Deal Desk', {
  origin: 'team_shared',
  access: 'viewer',
  allowed_actions: ['use', 'pin'],
  workspace: { kind: 'team', team_id: 't1' },
  shared_from: { team_id: 'ops', name: 'Sales' },
});

describe("AgentsList: another team's agents", () => {
  it("lists them in their own section after the team's agents, with the team they come from", async () => {
    inWorkspace('t1', 'viewer');
    state.preference.agents = [teamAgent, received];
    await render();
    expect(sectionIds()).toEqual(['user', 'teamShared']);
    expect(titlesIn(section('user'))).toEqual(['Ops bot']);
    expect(titlesIn(section('teamShared'))).toEqual(['Deal Desk']);
    expect(section('teamShared')?.textContent).toContain(
      'workspace.page.sharedFromTeams.title',
    );
    const tile = card('Deal Desk')!;
    expect(
      tile.querySelector('[data-testid="shared-from-meta"]')?.textContent,
    ).toBe('workspace.page.sharedFromTeams.from');
    expect(tile.querySelector('[data-testid="role-meta"]')).toBeNull();
  });

  it('shows no section while nothing is shared with the team', async () => {
    inWorkspace('t1');
    state.preference.agents = [teamAgent];
    await render();
    expect(sectionIds()).toEqual(['user']);
  });

  it('opens on its own route in a team', async () => {
    inWorkspace('t1');
    state.preference.agents = [teamAgent, received];
    await render('/agents/manage/shared-with-team');
    expect(sectionIds()).toEqual(['teamShared']);
  });

  it('has no such section in Personal; its route reads as everything', async () => {
    inWorkspace('personal');
    state.preference.agents = [own];
    await render('/agents/manage/shared-with-team');
    expect(sectionIds()).toEqual(['user']);
  });
});
