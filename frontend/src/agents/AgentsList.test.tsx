import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';

import type { Folder } from '../components/folders/types';
import type { Agent } from './types';

const dispatched = vi.hoisted(() => [] as unknown[]);
const state = vi.hoisted(() => ({
  preference: {
    token: null,
    selectedAgent: null,
    agents: [] as unknown[],
    templateAgents: [] as unknown[],
    sharedAgents: [] as unknown[],
  },
  folders: {
    agent: {
      items: [] as unknown[],
      loaded: true,
      loading: false,
      failed: false,
      latestRequestId: null,
      removedParents: {},
    },
    source: {
      items: [],
      loaded: false,
      loading: false,
      failed: false,
      latestRequestId: null,
      removedParents: {},
    },
  },
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector(state),
  useDispatch: () => (action: unknown) => {
    dispatched.push(action);
    return Promise.resolve(action);
  },
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const search = vi.hoisted(() => ({ query: '', total: 0 }));
const sections = vi.hoisted(() => ({
  template: [] as unknown[],
  user: [] as unknown[],
  team: [] as unknown[],
  shared: [] as unknown[],
}));
vi.mock('./hooks/useAgentSearch', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./hooks/useAgentSearch')>()),
  useAgentSearch: () => ({
    searchQuery: search.query,
    setSearchQuery: () => undefined,
    filteredAgentsBySection: sections,
    totalAgentsBySection: {
      template: 0,
      user: search.total,
      team: sections.team.length,
      shared: 0,
    },
    hasAnyAgents: search.total > 0,
    hasFilteredResults: sections.user.length > 0 || sections.team.length > 0,
    isDataLoaded: { template: true, user: true, team: true, shared: true },
  }),
}));
vi.mock('./hooks/useAgentsFetch', () => ({
  useAgentsFetch: () => ({
    isLoading: { template: false, user: false, team: false, shared: false },
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
vi.mock('./AgentCard', () => ({
  default: ({
    agent,
    section,
    folderLabel,
  }: {
    agent: Agent;
    section: string;
    folderLabel?: string;
  }) => (
    <div
      data-agent={agent.name}
      data-section={section}
      data-folder={folderLabel ?? ''}
    />
  ),
}));

import AgentsList from './AgentsList';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;
let location = '';

function LocationProbe() {
  const current = useLocation();
  location = current.pathname + current.search;
  return null;
}

const agent = (name: string, folder_id?: string, ownership?: 'team'): Agent =>
  ({ id: name, name, description: '', folder_id, ownership }) as Agent;
const folder = (
  id: string,
  name: string,
  parent_id: string | null = null,
  counts: Partial<Folder> = {},
): Folder => ({
  id,
  name,
  parent_id,
  item_count: 0,
  folder_count: 0,
  ...counts,
});

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  dispatched.length = 0;
  search.query = '';
  search.total = 0;
  sections.user = [];
  sections.team = [];
  state.preference.agents = [];
  state.folders.agent.items = [];
  state.folders.agent.loaded = true;
  state.folders.agent.failed = false;
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

const render = async (path: string) => {
  await act(async () =>
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <AgentsList />
        <LocationProbe />
      </MemoryRouter>,
    ),
  );
};

const empties = () =>
  Array.from(
    container.querySelectorAll<HTMLElement>('[data-slot="empty-state"]'),
  );
const agentNames = () =>
  Array.from(container.querySelectorAll<HTMLElement>('[data-agent]')).map(
    (el) => el.dataset.agent,
  );
const tiles = () =>
  Array.from(container.querySelectorAll<HTMLElement>('[data-folder-tile]')).map(
    (el) => el.querySelector('[data-slot="card-title"]')?.textContent,
  );
const buttonLabels = () =>
  Array.from(container.querySelectorAll('button')).map((b) => b.textContent);

const expectTextOnlySm = (el: HTMLElement | undefined) => {
  expect(el?.dataset.size).toBe('sm');
  expect(el?.querySelector('svg')).toBeNull();
};

describe('AgentsList empties', () => {
  it('says no search results once, as a small text-only EmptyState', async () => {
    search.query = 'zzz';
    search.total = 3;
    await render('/agents/manage');
    const found = empties().filter((el) =>
      el.textContent?.includes('agents.noSearchResults'),
    );
    expect(found).toHaveLength(1);
    expectTextOnlySm(found[0]);
    expect(found[0].textContent).toContain('agents.tryDifferentSearch');
  });

  it('says no search results in a filtered view the same way', async () => {
    search.query = 'zzz';
    search.total = 3;
    await render('/agents/manage/mine');
    const found = empties().filter((el) =>
      el.textContent?.includes('agents.noSearchResults'),
    );
    expect(found).toHaveLength(1);
    expectTextOnlySm(found[0]);
  });

  it('offers New Agent in an empty section, with no stray margin', async () => {
    await render('/agents/manage');
    const empty = empties().find((el) =>
      el.textContent?.includes('agents.sections.user.emptyState'),
    );
    expectTextOnlySm(empty);
    const button = empty?.querySelector('button');
    expect(button?.textContent).toBe('agents.newAgent');
    expect(button?.className).not.toContain('ml-2');
  });

  it('offers New Agent in an empty filtered view', async () => {
    await render('/agents/manage/mine');
    const empty = empties().find((el) =>
      el.textContent?.includes('agents.sections.user.emptyState'),
    );
    expectTextOnlySm(empty);
    expect(empty?.querySelector('button')?.textContent).toBe('agents.newAgent');
  });
});

describe('AgentsList folders', () => {
  const setUp = () => {
    state.folders.agent.items = [
      folder('f1', 'Customer-facing', null, { item_count: 1, folder_count: 1 }),
      folder('f2', 'Internal ops', null, { item_count: 1 }),
      folder('f3', 'EU desk', 'f1'),
    ];
    const own = [agent('Loose'), agent('Support', 'f1'), agent('HR bot', 'f2')];
    const team = [agent('Shared helper', 'f1', 'team')];
    sections.user = own;
    sections.team = team;
    search.total = own.length;
    state.preference.agents = [...own, ...team];
  };

  it('shows top-level folders as tiles and only unfiled agents', async () => {
    setUp();
    await render('/agents/manage');
    expect(tiles()).toEqual(['Customer-facing', 'Internal ops']);
    // My agents keeps the loose one; the Team section lists its own.
    expect(agentNames()).toEqual(['Loose', 'Shared helper']);
    expect(buttonLabels()).toEqual(
      expect.arrayContaining([
        'folders.newFolder',
        'agents.importAgent',
        'agents.newAgent',
      ]),
    );
  });

  it('opens a folder as its own place: crumbs, count line, nothing else', async () => {
    setUp();
    await render('/agents/manage?folder=f1');
    const crumbs = container.querySelector('nav[aria-label="breadcrumb"]');
    expect(crumbs?.textContent).toContain('folders.root.agent');
    expect(crumbs?.textContent).toContain('Customer-facing');
    expect(tiles()).toEqual(['EU desk']);
    // Own and team-shared agents filed here; the Team section is gone.
    expect(agentNames()).toEqual(['Support', 'Shared helper']);
    expect(container.textContent).not.toContain('agents.sections.team.title');
    expect(
      container.querySelector('button[aria-label="folders.menuLabel"]'),
    ).not.toBeNull();
  });

  it('keeps the whole trail for a link to a nested folder', async () => {
    setUp();
    await render('/agents/manage?folder=f3');
    const crumbs = container.querySelector('nav[aria-label="breadcrumb"]');
    expect(crumbs?.textContent).toContain('Customer-facing');
    expect(crumbs?.textContent).toContain('EU desk');
  });

  it('shows an empty folder with New agent', async () => {
    setUp();
    await render('/agents/manage?folder=f3');
    const empty = empties().find((el) =>
      el.textContent?.includes('folders.emptyTitle'),
    );
    expect(empty?.textContent).toContain('agents.folders.emptyHint');
    expect(empty?.querySelector('button')?.textContent).toBe('agents.newAgent');
  });

  it('searches flat: matching folders first, agents with their folder', async () => {
    setUp();
    search.query = 'desk';
    sections.user = [agent('Support', 'f1')];
    sections.team = [];
    await render('/agents/manage');
    expect(tiles()).toEqual(['EU desk']);
    const card = container.querySelector<HTMLElement>('[data-agent="Support"]');
    expect(card?.dataset.folder).toBe('Customer-facing');
  });

  it('sends an unknown folder back to the root with a toast', async () => {
    setUp();
    await render('/agents/manage?folder=gone');
    expect(location).toBe('/agents/manage');
    expect(
      dispatched.some(
        (action) =>
          (action as { type?: string }).type === 'actionToast/showActionToast',
      ),
    ).toBe(true);
  });

  it('shows a failed folder load with Retry', async () => {
    setUp();
    state.folders.agent.loaded = false;
    state.folders.agent.failed = true;
    state.folders.agent.items = [];
    await render('/agents/manage');
    const error = empties().find((el) =>
      el.textContent?.includes('folders.errors.loadFailed'),
    );
    expect(error?.textContent).toContain('retry');
  });
});
