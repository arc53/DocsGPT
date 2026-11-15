import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import type { MultiSelectPopoverItem } from '../components/MultiSelectPopover';
import { setRequestWorkspace } from '../workspace/requestWorkspace';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));
vi.mock('../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../hooks')>()),
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

const personal = { kind: 'personal', team_id: null };
const team = { kind: 'team', team_id: 't1' };

const mockState = {
  workspace: {
    current: 'personal',
    workspaces: [
      { id: 'personal', kind: 'personal', name: 'Personal' },
      { id: 't1', kind: 'team', name: 'Operations', role: 'editor' },
    ],
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
  preference: {
    token: null,
    sourceDocs: [] as unknown[],
    selectedAgent: null,
    prompts: [] as unknown[],
  },
  agentPreview: { queries: [], status: 'idle' },
};
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(mockState),
  useDispatch: () => () => undefined,
}));

vi.mock('../drafter/useDrafterConfig', () => ({
  useDrafterConfig: () => null,
  useDrafterConfigFor: () => null,
}));
vi.mock('../drafter/drafterApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../drafter/drafterApi')>()),
  streamDrafter: vi.fn(),
  getAgentGaps: async () => ({
    available: false,
    reason: 'off_on_this_instance',
    conversations: 0,
    needed: 10,
    days: 30,
    rows: [],
  }),
}));
vi.mock('../connectors/SignInAgainNotice', () => ({
  default: () => null,
  useSignInAgain: () => ({ reconnect: vi.fn(), modals: null }),
}));
vi.mock('../api/services/devicesService', () => ({
  default: { list: () => Promise.resolve({ devices: [] }) },
}));
vi.mock('../api/services/connectorsService', () => ({
  default: {
    listConnections: () => Promise.resolve({ connections: [] }),
    getCatalog: () => Promise.resolve({ success: true, connectors: [] }),
  },
}));

// The pickers draw their trigger and rows only.
vi.mock('../components/MultiSelectPopover', () => ({
  MultiSelectPopover: ({
    trigger,
    items,
    title,
  }: {
    trigger: React.ReactNode;
    items: MultiSelectPopoverItem[];
    title?: string;
  }) => (
    <div data-testid="picker" data-title={title}>
      {trigger}
      {items.map((item) => (
        <div
          key={item.id}
          data-item={item.id}
          data-group={item.group}
          data-heading={
            typeof item.groupHeading === 'string' ? item.groupHeading : ''
          }
        />
      ))}
    </div>
  ),
}));
vi.mock('./AgentPreview', () => ({ default: () => null }));
vi.mock('./components/GuardrailsSection', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./components/GuardrailsSection')>()),
  default: () => null,
  guardrailsIncomplete: () => false,
}));
vi.mock('../upload/Upload', () => ({ default: () => null }));
vi.mock('../modals/AddToolModal', () => ({ default: () => null }));
vi.mock('../modals/AgentDetailsModal', () => ({ default: () => null }));
vi.mock('../teams/ShareToTeamModal', () => ({ default: () => null }));
vi.mock('../navigation/SectionPills', () => ({ default: () => null }));
vi.mock('../navigation/SectionPageHeader', () => ({
  CurrentSectionHeader: () => null,
}));
vi.mock('../components/FileUpload', () => ({ FileUpload: () => null }));
vi.mock('../components/SourcesPopoverFooter', () => ({ default: () => null }));
vi.mock('../components/ToolIcon', () => ({ default: () => null }));

import NewAgent from './NewAgent';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

/** What the server answers, by path. */
const server = {
  tools: [] as unknown[],
  agent: {} as Record<string, unknown>,
};
const fetchMock = vi.fn(async (url: string) => {
  const body = url.includes('/api/get_tools')
    ? { success: true, tools: server.tools }
    : url.includes('/api/models')
      ? { models: [], default_model_id: '' }
      : url.includes('/api/get_agent')
        ? server.agent
        : {};
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
});

const headerOf = (path: string) => {
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes(path));
  const init = (call as unknown as [string, RequestInit] | undefined)?.[1];
  return (init?.headers as Record<string, string> | undefined)?.[
    'X-DocsGPT-Workspace'
  ];
};

const doc = (
  id: string,
  workspace: unknown,
  folderId: string | null = null,
) => ({
  id,
  name: `Doc ${id}`,
  date: '',
  model: 'm',
  workspace,
  folder_id: folderId,
});
const tool = (
  id: string,
  workspace: unknown,
  folderId: string | null = null,
) => ({
  id,
  name: 'memory',
  displayName: `Tool ${id}`,
  display_name: `Tool ${id}`,
  status: true,
  workspace,
  folder_id: folderId,
});

/** The rows of the picker with this title. */
const pickerRows = (title: string) =>
  Array.from(
    document.querySelectorAll<HTMLElement>(
      `[data-testid="picker"][data-title="${title}"] [data-item]`,
    ),
  );
const pickerIds = (title: string) =>
  pickerRows(title).map((row) => row.dataset.item);

describe('NewAgent in a workspace', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
    fetchMock.mockClear();
    setRequestWorkspace('personal', 0);
    mockState.workspace.current = 'personal';
    mockState.folders.tree.items = [];
    mockState.preference.sourceDocs = [];
    mockState.preference.prompts = [];
    server.tools = [];
    server.agent = {};
  });

  const inTeam = () => {
    mockState.workspace.current = 't1';
    setRequestWorkspace('t1', 1);
  };
  const mountNew = () =>
    act(async () => {
      root.render(
        <MemoryRouter>
          <NewAgent mode="new" />
        </MemoryRouter>,
      );
    });
  const mountEdit = () =>
    act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/edit/agent-1']}>
          <Routes>
            <Route
              path="/agents/edit/:agentId"
              element={<NewAgent mode="edit" />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });

  it("asks for the tools and models of the team it's in", async () => {
    inTeam();
    await mountNew();
    expect(headerOf('/api/get_tools')).toBe('t1');
    expect(headerOf('/api/models')).toBe('t1');
  });

  it("never lists another workspace's item a stale list still holds", async () => {
    inTeam();
    mockState.preference.sourceDocs = [
      doc('mine', personal),
      doc('ours', team),
    ];
    server.tools = [tool('my-tool', personal), tool('our-tool', team)];
    await mountNew();
    expect(pickerIds('conversation.sources.knowledge')).toEqual(['ours']);
    expect(pickerIds('settings.tools.label')).toEqual(['our-tool']);
  });

  it("lists nothing of Personal's for a team agent opened from Personal", async () => {
    // The page switches to the agent's team; until it has, the lists it
    // holds are Personal's and none of them may show.
    server.agent = {
      id: 'agent-1',
      name: 'Ops agent',
      agent_type: 'classic',
      workspace: team,
    };
    mockState.preference.sourceDocs = [doc('mine', personal)];
    server.tools = [tool('my-tool', personal)];
    await mountEdit();
    expect(pickerIds('conversation.sources.knowledge')).toEqual([]);
    expect(pickerIds('settings.tools.label')).toEqual([]);
  });

  it("lists the agent's folder first in the knowledge and tools pickers", async () => {
    mockState.folders.tree.items = [
      { id: 'f1', name: 'Carriers', parent_id: null, counts: { source: 1 } },
    ];
    mockState.preference.sourceDocs = [
      doc('loose', personal),
      doc('filed', personal, 'f1'),
    ];
    server.tools = [
      tool('loose-tool', personal),
      tool('filed-tool', personal, 'f1'),
    ];
    server.agent = {
      id: 'agent-1',
      name: 'Carrier agent',
      agent_type: 'classic',
      workspace: personal,
      folder_id: 'f1',
    };
    await mountEdit();
    const knowledge = pickerRows('conversation.sources.knowledge');
    expect(knowledge[0].dataset.item).toBe('filed');
    expect(knowledge[0].dataset.heading).toBe(
      'workspace.pickers.inAgentFolder',
    );
    const tools = pickerRows('settings.tools.label');
    expect(tools.map((row) => row.dataset.item)).toEqual([
      'filed-tool',
      'loose-tool',
    ]);
    expect(tools[0].dataset.heading).toBe('workspace.pickers.inAgentFolder');
  });

  it("lists the agent's folder first in the prompt picker", async () => {
    mockState.folders.tree.items = [
      { id: 'f1', name: 'Carriers', parent_id: null, counts: { prompt: 1 } },
    ];
    mockState.preference.prompts = [
      { id: 'default', name: 'default', type: 'public' },
      {
        id: 'loose',
        name: 'Loose',
        type: 'private',
        origin: 'own',
        access: 'owner',
        workspace: personal,
      },
      {
        id: 'filed',
        name: 'Filed',
        type: 'private',
        origin: 'own',
        access: 'owner',
        workspace: personal,
        folder_id: 'f1',
        folder_path: [{ id: 'f1', name: 'Carriers' }],
      },
    ];
    server.agent = {
      id: 'agent-1',
      name: 'Carrier agent',
      agent_type: 'classic',
      workspace: personal,
      folder_id: 'f1',
    };
    await mountEdit();
    const trigger = container.querySelector<HTMLButtonElement>(
      '[data-slot="combobox-trigger"]',
    )!;
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
    const groups = Array.from(document.body.querySelectorAll('[cmdk-group]'));
    expect(groups[0].querySelector('[cmdk-group-heading]')?.textContent).toBe(
      'workspace.pickers.inAgentFolder',
    );
    expect(
      Array.from(groups[0].querySelectorAll('[cmdk-item]')).map((row) =>
        row.getAttribute('data-value'),
      ),
    ).toEqual(['filed']);
  });

  it("never lists another workspace's prompt", async () => {
    inTeam();
    mockState.preference.prompts = [
      { id: 'default', name: 'default', type: 'public' },
      { id: 'mine', name: 'Mine', type: 'private', workspace: personal },
      {
        id: 'ours',
        name: 'Ours',
        type: 'team',
        origin: 'team',
        workspace: team,
      },
    ];
    await mountNew();
    const trigger = container.querySelector<HTMLButtonElement>(
      '[data-slot="combobox-trigger"]',
    )!;
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
    expect(
      Array.from(document.body.querySelectorAll('[cmdk-item]')).map((row) =>
        row.getAttribute('data-value'),
      ),
    ).toEqual(['default', 'ours']);
  });
});
