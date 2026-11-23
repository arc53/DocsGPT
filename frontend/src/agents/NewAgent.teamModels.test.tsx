import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import type { MultiSelectPopoverItem } from '../components/MultiSelectPopover';
import { setRequestWorkspace } from '../workspace/requestWorkspace';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // The names a line carries show after the key.
    t: (key: string, opts?: Record<string, unknown>) =>
      typeof opts?.names === 'string' ? `${key}:${opts.names}` : key,
    i18n: { language: 'en' },
  }),
}));
vi.mock('../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../hooks')>()),
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

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

const MODELS = [
  { id: 'gpt', display_name: 'GPT', provider: 'openai', source: 'builtin' },
  { id: 'ops', display_name: 'Ops model', provider: 'openai', source: 'team' },
];

/** What the server answers, by path. */
const server = {
  agent: {} as Record<string, unknown>,
  update: null as null | { status: number; body: unknown },
};
const fetchMock = vi.fn(async (url: string) => {
  const reply = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  if (url.includes('/api/update_agent') && server.update)
    return reply(server.update.body, server.update.status);
  return reply(
    url.includes('/api/get_tools')
      ? { success: true, tools: [] }
      : url.includes('/api/models')
        ? { models: MODELS, default_model_id: 'gpt' }
        : url.includes('/api/get_agent')
          ? server.agent
          : {},
  );
});

/** The rows of the picker with this title. */
const pickerRows = (title: string) =>
  Array.from(
    document.querySelectorAll<HTMLElement>(
      `[data-testid="picker"][data-title="${title}"] [data-item]`,
    ),
  );

describe("NewAgent with a team's custom models", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    mockState.workspace.current = 't1';
    setRequestWorkspace('t1', 1);
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
    server.agent = {};
    server.update = null;
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

  const editTeamAgent = async (models: string[]) => {
    server.agent = {
      id: 'agent-1',
      name: 'Ops agent',
      description: 'd',
      status: 'published',
      agent_type: 'classic',
      prompt_id: 'default',
      workspace: team,
      access: 'editor',
      allowed_actions: ['edit', 'view'],
      models,
      default_model_id: models[0],
    };
    await mountEdit();
  };

  const rename = (value: string) =>
    act(async () => {
      const input = container.querySelector<HTMLInputElement>(
        'input[placeholder="agents.form.placeholders.agentName"]',
      )!;
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

  const button = (label: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === label,
    )!;

  it("lists the team's models under Team models, after the catalog", async () => {
    await editTeamAgent(['gpt']);
    const rows = pickerRows('agents.form.modelsPopup.title');
    expect(rows.map((row) => [row.dataset.item, row.dataset.group])).toEqual([
      ['gpt', 'settings.customModels.modelsGroup.builtin'],
      ['ops', 'settings.customModels.team.pickerGroup'],
    ]);
  });

  it('names the models a refused save named, and Remove takes them off', async () => {
    server.update = {
      status: 400,
      body: {
        success: false,
        error: 'custom_model_personal_only',
        message: 'A team agent can use only the team models',
        models: ['ops', 'mine'],
      },
    };
    await editTeamAgent(['ops', 'mine', 'gpt']);
    await rename('Ops agent 2');
    await act(async () => button('agents.form.buttons.save').click());
    const alerts = Array.from(container.querySelectorAll('[role="alert"]')).map(
      (node) => node.textContent,
    );
    // The sentence once, in the toolbar's alert; the field names the models.
    expect(
      alerts.filter((text) =>
        text?.includes('settings.customModels.team.errors.personalOnly'),
      ),
    ).toHaveLength(1);
    const line = alerts.find((text) =>
      text?.includes('agents.form.refusedModels.line'),
    );
    expect(line).toContain('Ops model');
    expect(line).toContain('agents.form.refusedModels.unlisted');

    server.update = null;
    await act(async () => button('agents.form.refusedModels.remove').click());
    expect(container.textContent).not.toContain(
      'agents.form.refusedModels.line',
    );
    await act(async () => button('agents.form.buttons.save').click());
    const sent = fetchMock.mock.calls
      .filter(([url]) => String(url).includes('/api/update_agent'))
      .at(-1) as unknown as [string, RequestInit];
    const form = sent[1].body as FormData;
    expect(JSON.parse(String(form.get('models')))).toEqual(['gpt']);
    expect(form.get('default_model_id')).toBe('gpt');
  });
});
