import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

import type { Folder } from '../components/folders/types';
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
const sharedWithMe = agent('From Priya', {
  origin: 'shared',
  access: 'viewer',
  allowed_actions: ['use', 'pin'],
  workspace: { kind: 'personal', team_id: null },
  created_by: { user_id: 'priya', label: 'Priya' },
});
const teamAgent = agent('Ops bot', {
  origin: 'team',
  access: 'editor',
  allowed_actions: ['use', 'pin', 'view', 'edit'],
  workspace: { kind: 'team', team_id: 't1' },
  created_by: { user_id: 'dana', label: 'Dana' },
});
const discovered = agent('Public helper', { shared_token: 'tok' });
const template = agent('Starter', { id: 'tpl' });

const folder = (
  id: string,
  name: string,
  counts: Folder['counts'],
): Folder => ({
  id,
  name,
  parent_id: null,
  counts,
  item_count: 0,
  folder_count: 0,
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
const buttonLabels = () =>
  Array.from(container.querySelectorAll('button')).map((b) => b.textContent);

describe('AgentsList in Personal', () => {
  it('lists own agents, then Shared with you; no Team section', async () => {
    state.preference.agents = [own, sharedWithMe];
    await render();
    expect(sectionIds()).toEqual(['user', 'sharedWithYou']);
    expect(titlesIn(section('user'))).toEqual(['Mine']);
    expect(titlesIn(section('sharedWithYou'))).toEqual(['From Priya']);
    expect(section('sharedWithYou')?.textContent).toContain(
      'workspace.page.sharedWithYou',
    );
    expect(container.textContent).not.toContain('agents.sections.team.title');
  });

  it("names a shared agent's owner and the reader's role; nothing on own", async () => {
    state.preference.agents = [own, sharedWithMe];
    await render();
    const shared = card('From Priya')!;
    expect(
      shared.querySelector('[data-testid="creator-meta"]')?.textContent,
    ).toBe('Priya');
    expect(shared.querySelector('[data-testid="role-meta"]')).not.toBeNull();
    const mine = card('Mine')!;
    expect(mine.querySelector('[data-testid="creator-meta"]')).toBeNull();
    expect(mine.querySelector('[data-testid="role-meta"]')).toBeNull();
  });

  it('shows the workspace line and keeps Discovered', async () => {
    state.preference.agents = [own];
    state.preference.sharedAgents = [discovered];
    await render();
    expect(
      container.querySelector('[data-testid="workspace-line"]'),
    ).not.toBeNull();
    expect(sectionIds()).toContain('shared');
  });

  it('opens the old Team route on Shared with you', async () => {
    state.preference.agents = [own, sharedWithMe];
    await render('/agents/manage/team');
    expect(sectionIds()).toEqual(['sharedWithYou']);
  });

  it('offers Move to team on the agent cards', async () => {
    state.preference.agents = [own];
    await render();
    expect(moveCalls).toContain('agent');
  });
});

describe('AgentsList in a team', () => {
  it("lists the team's agents with who added them, no role, no Shared with you", async () => {
    inWorkspace('t1');
    state.preference.agents = [teamAgent];
    state.preference.sharedAgents = [discovered];
    await render();
    expect(sectionIds()).toEqual(['user']);
    expect(section('user')?.textContent).toContain(
      'agents.sections.team.title',
    );
    const tile = card('Ops bot')!;
    expect(
      tile.querySelector('[data-testid="creator-meta"]')?.textContent,
    ).toBe('Dana');
    expect(tile.querySelector('[data-testid="role-meta"]')).toBeNull();
    expect(container.textContent).not.toContain('workspace.page.sharedWithYou');
  });

  it('gives an Editor New agent, Import and New folder', async () => {
    inWorkspace('t1', 'editor');
    state.preference.agents = [teamAgent];
    await render();
    expect(buttonLabels()).toEqual(
      expect.arrayContaining([
        'agents.newAgent',
        'agents.importAgent',
        'folders.newFolder',
      ]),
    );
  });

  it('gives a Viewer no create buttons, even in an empty list', async () => {
    inWorkspace('t1', 'viewer');
    await render();
    const labels = buttonLabels();
    expect(labels).not.toContain('agents.newAgent');
    expect(labels).not.toContain('agents.importAgent');
    expect(labels).not.toContain('folders.newFolder');
  });

  it('keeps Templates, with Duplicate only for an Editor', async () => {
    state.preference.templateAgents = [template];
    inWorkspace('t1', 'viewer');
    await render();
    expect(sectionIds()).toContain('template');
    expect(
      card('Starter')?.querySelector(
        'button[aria-label="agents.card.actions"]',
      ),
    ).toBeFalsy();

    await act(async () => root.unmount());
    root = createRoot(container);
    inWorkspace('t1', 'editor');
    await render();
    expect(
      card('Starter')?.querySelector(
        'button[aria-label="agents.card.actions"]',
      ),
    ).toBeTruthy();
  });

  it('hides a Discovered or Shared with you route, showing the list', async () => {
    inWorkspace('t1');
    state.preference.agents = [teamAgent];
    await render('/agents/manage/discovered');
    expect(sectionIds()).toEqual(['user']);
  });
});

describe('AgentsList folders by kind', () => {
  it('shows folders holding agents or nothing, not tool-only ones', async () => {
    state.folders.tree.items = [
      folder('f1', 'Support', { agent: 2 }),
      folder('f2', 'Integrations', { tool: 3 }),
      folder('f3', 'Fresh', {}),
    ];
    state.preference.agents = [own];
    await render();
    const tiles = Array.from(
      container.querySelectorAll<HTMLElement>('[data-folder-tile]'),
    ).map((el) => el.dataset.folderTile);
    expect(tiles).toEqual(['f3', 'f1']);
  });
});
