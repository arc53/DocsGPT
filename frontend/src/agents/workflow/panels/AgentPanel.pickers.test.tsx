import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import type { Node } from 'reactflow';
import type { Mock } from 'vitest';

import type { Doc } from '../../../models/misc';
import type { UserTool } from '../workflowHelpers';

const media = vi.hoisted(() => ({ isMobile: false, isDesktop: true }));
vi.mock('../../../hooks', () => ({
  useMediaQuery: () => media,
  useDarkTheme: () => [false, () => undefined],
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: unknown) =>
      typeof opts === 'string'
        ? opts
        : opts && typeof opts === 'object' && 'count' in opts
          ? `${key}:${(opts as { count: number }).count}`
          : key,
  }),
}));

const store = vi.hoisted(() => ({
  state: {} as Record<string, unknown>,
  dispatch: vi.fn(),
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(store.state),
  useDispatch: () => store.dispatch,
}));
vi.mock('../../../connectors/connectorsSlice', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  loadConnectors: (arg: unknown) => ({ type: 'connectors/load', arg }),
}));

// The upload dialog, as a stub that finishes an upload on demand.
const upload = vi.hoisted(() => ({
  props: null as null | {
    close: () => void;
    onSuccessfulUpload?: (sourceId?: string) => void;
    onBrowseConnectors?: () => void;
    onNavigate?: unknown;
  },
}));
vi.mock('../../../upload/Upload', () => ({
  default: (props: NonNullable<typeof upload.props>) => {
    upload.props = props;
    return <div data-testid="upload" />;
  },
}));
// The Add tool dialog, as a stub that reports a new tool on demand.
const addTool = vi.hoisted(() => ({
  props: null as null | {
    modalState: string;
    setModalState: (state: string) => void;
    onToolsCreated: (toolIds: string[]) => void;
    onNavigate?: (to: string) => void;
  },
}));
vi.mock('../../../modals/AddToolModal', () => ({
  default: (props: NonNullable<typeof addTool.props>) => {
    addTool.props = props;
    return null;
  },
}));
const devices = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock('../../../api/services/devicesService', () => ({ default: devices }));
vi.mock('../components/PromptTextArea', () => ({
  default: () => null,
  extractUpstreamVariables: () => [],
}));
vi.mock('../components/NodeDocumentsControl', () => ({ default: () => null }));

import AgentPanel from './AgentPanel';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const doc = (id: string, name: string, extra: Partial<Doc> = {}): Doc => ({
  id,
  name,
  date: '2026-10-01',
  model: 'm',
  ...extra,
});

const DOCS: Doc[] = [
  doc('own-1', 'Handbook'),
  doc('team-1', 'Team wiki', { ownership: 'team' }),
];

const TOOLS: UserTool[] = [
  { id: 'jira', name: 'api_tool', displayName: 'Jira API' },
  { id: 'brave', name: 'brave', displayName: 'Brave Search' },
];

type UpdateFn = (data: Record<string, unknown>) => void;

const makeNode = (config: Record<string, unknown> = {}): Node => ({
  id: 'agent_1',
  type: 'agent',
  position: { x: 0, y: 0 },
  data: { config: { sources: [], tools: [], ...config } },
});

describe('AgentPanel knowledge and tool pickers', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    media.isMobile = false;
    upload.props = null;
    addTool.props = null;
    devices.list.mockReset();
    devices.list.mockResolvedValue({ devices: [] });
    store.dispatch.mockClear();
    store.state = {
      preference: { token: 'tok', sourceDocs: DOCS },
      connectors: {
        connections: [],
        catalog: [],
        loaded: true,
        loading: false,
      },
    };
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (
    node: Node,
    {
      tools = TOOLS,
      attachedTools = [],
      attachedSources = [],
      onUpdate = vi.fn<UpdateFn>(),
      onReloadTools = vi.fn(async () => tools),
      onNavigateAway,
      onLeaveTo,
      onReconnect,
    }: {
      tools?: UserTool[];
      attachedTools?: { id: string; label: string }[];
      attachedSources?: { id: string; label: string }[];
      onUpdate?: Mock<UpdateFn>;
      onReloadTools?: () => Promise<UserTool[]>;
      onNavigateAway?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
      onLeaveTo?: (to: string) => void;
      onReconnect?: (connection: { id: string }, mcpToolId?: string) => void;
    } = {},
  ) => {
    await act(async () =>
      root.render(
        <MemoryRouter>
          <AgentPanel
            node={node}
            onUpdate={onUpdate}
            nodes={[node]}
            edges={[]}
            availableModels={[]}
            availableTools={tools}
            attachedTools={attachedTools}
            attachedSources={attachedSources}
            documentOptions={[]}
            jsonSchemaText=""
            jsonSchemaError={null}
            modelSupportsStructuredOutput
            onJsonSchemaChange={vi.fn()}
            onReloadTools={onReloadTools}
            onNavigateAway={onNavigateAway}
            onLeaveTo={onLeaveTo}
            onReconnect={onReconnect}
          />
        </MemoryRouter>,
      ),
    );
    return onUpdate;
  };

  const knowledgeSection = () =>
    Array.from(container.querySelectorAll('section')).find((section) =>
      section.textContent?.includes('agents.workflow.builder.knowledge'),
    )!;
  const triggers = () =>
    Array.from(
      knowledgeSection().querySelectorAll<HTMLElement>('[role="combobox"]'),
    );
  const sourcesTrigger = () => triggers()[0];
  const toolsTrigger = () => triggers()[1];
  const open = async (trigger: HTMLElement) =>
    act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
  const popover = () =>
    document.querySelector<HTMLElement>('[data-slot="popover-content"]')!;
  const rows = () =>
    Array.from(
      popover().querySelectorAll<HTMLElement>('[data-slot="command-item"]'),
    );
  const row = (label: string) =>
    rows().find((el) => el.textContent?.includes(label))!;
  const headings = () =>
    Array.from(popover().querySelectorAll('[cmdk-group-heading]')).map(
      (el) => el.textContent,
    );

  it('keeps the combobox field trigger, showing the picked names', async () => {
    await render(makeNode({ sources: ['own-1'], tools: ['jira', 'brave'] }));
    expect(triggers()).toHaveLength(2);
    for (const trigger of triggers()) {
      expect(trigger.dataset.slot).toBe('multi-select-trigger');
      expect(trigger.dataset.variant).toBe('combobox');
      expect(trigger.dataset.size).toBe('field');
    }
    const chips = (trigger: HTMLElement) =>
      Array.from(trigger.querySelectorAll('[data-slot="badge"]')).map(
        (chip) => chip.textContent,
      );
    expect(chips(sourcesTrigger())).toEqual(['Handbook']);
    expect(chips(toolsTrigger())).toEqual(['Jira API', 'Brave Search']);
  });

  it('shows the placeholders while nothing is picked', async () => {
    await render(makeNode());
    expect(sourcesTrigger().textContent).toBe(
      'agents.form.placeholders.selectSources',
    );
    expect(toolsTrigger().textContent).toBe(
      'agents.form.placeholders.selectTools',
    );
    expect(sourcesTrigger().hasAttribute('data-placeholder')).toBe(true);
  });

  it('lets each field label name its trigger', async () => {
    await render(makeNode());
    for (const trigger of triggers()) {
      expect(trigger.id).not.toBe('');
      expect(
        knowledgeSection().querySelector(`label[for="${trigger.id}"]`),
      ).not.toBeNull();
    }
  });

  it('opens the shared Knowledge picker: title, search, groups and footer', async () => {
    await render(makeNode());
    await open(sourcesTrigger());
    expect(popover().querySelector('h3')?.textContent).toBe(
      'conversation.sources.knowledge',
    );
    expect(popover().querySelector('input')?.getAttribute('placeholder')).toBe(
      'agents.form.sourcePopup.searchPlaceholder',
    );
    expect(headings()).toEqual([
      'conversation.sources.groupOwn',
      'conversation.sources.groupTeam',
    ]);
    const footer = document.querySelector('[data-slot="multi-select-footer"]')!;
    const link = footer.querySelector('a')!;
    expect(link.textContent).toBe('settings.sources.goToSources');
    expect(link.getAttribute('href')).toBe('/settings/knowledge');
    expect(footer.textContent).toContain('settings.sources.uploadNew');
  });

  it('saves the picked sources as ids, as before', async () => {
    const onUpdate = await render(makeNode({ sources: ['own-1'] }));
    await open(sourcesTrigger());
    await act(async () => row('Team wiki').click());
    expect(onUpdate).toHaveBeenLastCalledWith({
      config: expect.objectContaining({ sources: ['own-1', 'team-1'] }),
    });
    await act(async () => row('Handbook').click());
    expect(onUpdate).toHaveBeenLastCalledWith({
      config: expect.objectContaining({ sources: [] }),
    });
  });

  it('lists what was picked in a Selected group and ticks it', async () => {
    await render(makeNode({ sources: ['team-1'] }));
    await open(sourcesTrigger());
    // The mock t returns the fallback, 'Selected'.
    expect(headings()[0]).toBe('Selected');
    expect(row('Team wiki').dataset.checked).toBe('true');
    expect(row('Handbook').dataset.checked).toBeUndefined();
  });

  it('opens the shared Tools picker: title, search, groups and a Go to Tools footer', async () => {
    await render(makeNode());
    await open(toolsTrigger());
    expect(popover().querySelector('h3')?.textContent).toBe(
      'settings.tools.label',
    );
    expect(popover().querySelector('input')?.getAttribute('placeholder')).toBe(
      'settings.tools.searchPlaceholder',
    );
    expect(rows().map((el) => el.querySelector('p')?.textContent)).toEqual(
      expect.arrayContaining(['Jira API', 'Brave Search']),
    );
    const footer = document.querySelector('[data-slot="multi-select-footer"]')!;
    const link = footer.querySelector('a')!;
    expect(link.textContent).toBe('settings.tools.manageTools');
    expect(link.getAttribute('href')).toBe('/settings/tools');
    const add = footer.querySelector('button')!;
    expect(add.textContent).toBe('settings.tools.addTool');
    await act(async () => add.click());
    expect(addTool.props?.modalState).toBe('ACTIVE');
  });

  it('hands the Go to links to the builder, which asks before leaving', async () => {
    const onNavigateAway = vi.fn((event: React.MouseEvent) =>
      event.preventDefault(),
    );
    await render(makeNode(), { onNavigateAway });
    await open(toolsTrigger());
    await act(async () =>
      document
        .querySelector<HTMLAnchorElement>(
          '[data-slot="multi-select-footer"] a',
        )!
        .click(),
    );
    expect(onNavigateAway).toHaveBeenCalledTimes(1);
    await act(async () => root.render(<></>));
    await render(makeNode(), { onNavigateAway });
    await open(sourcesTrigger());
    await act(async () =>
      document
        .querySelector<HTMLAnchorElement>(
          '[data-slot="multi-select-footer"] a',
        )!
        .click(),
    );
    expect(onNavigateAway).toHaveBeenCalledTimes(2);
  });

  it('puts a tool added from the footer on the node', async () => {
    const added: UserTool = { id: 'new', name: 'ntfy', displayName: 'ntfy' };
    const onReloadTools = vi.fn(async () => [...TOOLS, added]);
    const onUpdate = vi.fn<UpdateFn>();
    await render(makeNode({ tools: ['brave'] }), { onUpdate, onReloadTools });
    await act(async () => addTool.props!.onToolsCreated(['new']));
    expect(onReloadTools).toHaveBeenCalled();
    expect(onUpdate).toHaveBeenLastCalledWith({
      config: expect.objectContaining({ tools: ['brave', 'new'] }),
    });
  });

  // A connected service sets up several tools; one the picker doesn't
  // offer stays off.
  it('puts every listed tool a connect set up on the node', async () => {
    const made = [
      { id: 'tool-a', name: 'telegram', displayName: 'Telegram' },
      { id: 'tool-b', name: 'telegram', displayName: 'Telegram 2' },
    ] as UserTool[];
    const onUpdate = vi.fn<UpdateFn>();
    await render(makeNode(), {
      onUpdate,
      onReloadTools: vi.fn(async () => [...TOOLS, ...made]),
    });
    await act(async () =>
      addTool.props!.onToolsCreated(['tool-a', 'tool-b', 'unlisted']),
    );
    expect(onUpdate).toHaveBeenLastCalledWith({
      config: expect.objectContaining({ tools: ['tool-a', 'tool-b'] }),
    });
  });

  it('leaves for a page from Add tool through the builder', async () => {
    const onLeaveTo = vi.fn();
    await render(makeNode(), { onLeaveTo });
    addTool.props!.onNavigate!('/settings/connectors');
    expect(onLeaveTo).toHaveBeenCalledWith('/settings/connectors');
  });

  it("shows a device's Online or Offline, as the other tool pickers do", async () => {
    devices.list.mockResolvedValue({
      devices: [{ id: 'dev-1', last_seen_at: new Date().toISOString() }],
    });
    const device = {
      id: 'tool-dev',
      name: 'remote_device',
      displayName: 'Laptop',
      config: { device_id: 'dev-1' },
    } as UserTool;
    await render(makeNode(), { tools: [...TOOLS, device] });
    await open(toolsTrigger());
    expect(devices.list).toHaveBeenCalledWith('tok');
    expect(row('Laptop').textContent).toContain('settings.devices.online');
  });

  it('saves the picked tools as ids, as before', async () => {
    const onUpdate = await render(makeNode({ tools: ['brave'] }));
    await open(toolsTrigger());
    await act(async () => row('Jira API').click());
    expect(onUpdate).toHaveBeenLastCalledWith({
      config: expect.objectContaining({ tools: ['brave', 'jira'] }),
    });
  });

  it('says so when there is nothing to pick', async () => {
    store.state = {
      ...store.state,
      preference: { token: 'tok', sourceDocs: [] },
    };
    await render(makeNode(), { tools: [] });
    await open(toolsTrigger());
    expect(popover().textContent).toContain('settings.tools.noToolsFound');
    await act(async () => root.render(<></>));
    await render(makeNode(), { tools: [] });
    await open(sourcesTrigger());
    expect(popover().textContent).toContain(
      'settings.sources.noKnowledgeFound',
    );
  });

  it('refreshes the connections when a picker opens', async () => {
    await render(makeNode());
    expect(store.dispatch).not.toHaveBeenCalled();
    await open(toolsTrigger());
    expect(store.dispatch).toHaveBeenCalledWith({
      type: 'connectors/load',
      arg: { token: 'tok' },
    });
  });

  it('draws the kind track only past ten rows', async () => {
    await render(makeNode());
    await open(sourcesTrigger());
    expect(document.querySelector('[data-slot="multi-select-filters"]')).toBe(
      null,
    );
    await act(async () => root.render(<></>));
    store.state = {
      ...store.state,
      preference: {
        token: 'tok',
        sourceDocs: [
          ...Array.from({ length: 8 }, (_, i) => doc(`f${i}`, `File ${i}`)),
          ...Array.from({ length: 4 }, (_, i) =>
            doc(`w${i}`, `Wiki ${i}`, { type: 'wiki' }),
          ),
        ],
      },
    };
    await render(makeNode());
    await open(sourcesTrigger());
    const filters = document.querySelector(
      '[data-slot="multi-select-filters"]',
    )!;
    expect(
      filters.querySelector('[aria-label="settings.sources.kindFilterLabel"]'),
    ).not.toBeNull();
    const wikis = Array.from(
      filters.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent?.includes('settings.sources.kinds.wikis'))!;
    await act(async () => wikis.click());
    expect(rows()).toHaveLength(4);
  });

  it('keeps a remove-only row for an attached item the caller cannot list', async () => {
    const onUpdate = await render(
      makeNode({ tools: ['jira', 'owners'], sources: ['owner-src'] }),
      {
        attachedTools: [{ id: 'owners', label: 'Owner Jira' }],
        attachedSources: [{ id: 'owner-src', label: 'Owner docs' }],
      },
    );
    // The chip reads the plain name; only the row says who added it.
    expect(sourcesTrigger().textContent).toBe('Owner docs');
    expect(toolsTrigger().textContent).toContain('Owner Jira');
    expect(toolsTrigger().textContent).not.toContain(
      'agents.form.sponsors.addedByOther',
    );
    await open(toolsTrigger());
    expect(row('Owner Jira').textContent).toContain(
      'agents.form.sponsors.addedByOther',
    );
    expect(row('Jira API').textContent).not.toContain(
      'agents.form.sponsors.addedByOther',
    );
    await act(async () => row('Owner Jira').click());
    expect(onUpdate).toHaveBeenLastCalledWith({
      config: expect.objectContaining({ tools: ['jira'] }),
    });
  });

  it('attaches a source uploaded from the footer while the node is open', async () => {
    const onUpdate = await render(makeNode({ sources: ['own-1'] }));
    await open(sourcesTrigger());
    const uploadButton = Array.from(
      document.querySelectorAll<HTMLButtonElement>(
        '[data-slot="multi-select-footer"] button',
      ),
    ).find((b) => b.textContent === 'settings.sources.uploadNew')!;
    await act(async () => uploadButton.click());
    expect(popover()).toBeNull();
    expect(upload.props).not.toBeNull();
    // Leaving the builder would lose the unsaved workflow.
    expect(upload.props!.onBrowseConnectors).toBeUndefined();
    await act(async () => upload.props!.onSuccessfulUpload?.('new-src'));
    expect(onUpdate).toHaveBeenLastCalledWith({
      config: expect.objectContaining({ sources: ['own-1', 'new-src'] }),
    });
  });

  // As in the agent builder: Browse connectors asks first while the
  // workflow has unsaved changes.
  it("sends Upload's Browse connectors through the builder", async () => {
    const onLeaveTo = vi.fn();
    await render(makeNode(), { onLeaveTo });
    await open(sourcesTrigger());
    const uploadButton = Array.from(
      document.querySelectorAll<HTMLButtonElement>(
        '[data-slot="multi-select-footer"] button',
      ),
    ).find((b) => b.textContent === 'settings.sources.uploadNew')!;
    await act(async () => uploadButton.click());
    upload.props!.onBrowseConnectors!();
    expect(onLeaveTo).toHaveBeenCalledWith(
      '/settings/connectors?capability=sync',
    );
    // A connect run started from Upload leaves through it too.
    expect(upload.props!.onNavigate).toBe(onLeaveTo);
  });

  it('offers to sign a broken connection behind its tools in again', async () => {
    store.state = {
      ...store.state,
      connectors: {
        connections: [
          {
            id: 'conn-1',
            connector_key: 'telegram',
            name: 'Ops bot',
            status: 'reconnect_needed',
          },
        ],
        catalog: [],
        loaded: true,
        loading: false,
      },
    };
    const onReconnect = vi.fn();
    await render(makeNode(), {
      tools: [
        ...TOOLS,
        {
          id: 'tg',
          name: 'telegram',
          displayName: 'Telegram',
          connection_id: 'conn-1',
        } as UserTool,
      ],
      onReconnect,
    });
    await open(toolsTrigger());
    const notice = Array.from(
      document.querySelectorAll<HTMLButtonElement>(
        '[data-slot="multi-select-footer"] button',
      ),
    ).find((b) => b.textContent?.includes('settings.connectors'))!;
    expect(notice).toBeDefined();
    await act(async () => notice.click());
    expect(onReconnect).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'conn-1' }),
      undefined,
    );
  });

  it('leaves the node alone when an upload finishes after the panel closed', async () => {
    const onUpdate = await render(makeNode());
    await open(sourcesTrigger());
    const uploadButton = Array.from(
      document.querySelectorAll<HTMLButtonElement>(
        '[data-slot="multi-select-footer"] button',
      ),
    ).find((b) => b.textContent === 'settings.sources.uploadNew')!;
    await act(async () => uploadButton.click());
    const finish = upload.props!.onSuccessfulUpload!;
    await act(async () => root.render(<></>));
    onUpdate.mockClear();
    finish('new-src');
    expect(onUpdate).not.toHaveBeenCalled();
  });
});
