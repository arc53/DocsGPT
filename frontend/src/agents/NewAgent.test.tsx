import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';

import type { MultiSelectPopoverItem } from '../components/MultiSelectPopover';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

// The prompt picker turns into a bottom sheet on a phone.
const media = vi.hoisted(() => ({ isMobile: false, isDesktop: true }));
vi.mock('../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../hooks')>()),
  useMediaQuery: () => media,
}));

const mockState = {
  preference: {
    token: null,
    sourceDocs: [],
    selectedAgent: null,
    prompts: [],
    agentFolders: [],
  },
  agentPreview: { queries: [], status: 'idle' },
};

const mocks = vi.hoisted(() => {
  const jsonResponse = (body: unknown, ok = true) =>
    Promise.resolve({ ok, json: () => Promise.resolve(body) });
  return {
    jsonResponse,
    submitResult: undefined as void | Promise<unknown>,
    dispatch: vi.fn(),
    getAgent: vi.fn(() => jsonResponse({})),
    getAgentDefaults: vi.fn(() => jsonResponse({ success: true })),
    createAgent: vi.fn(() => jsonResponse({ message: 'Name is taken' }, false)),
    createPrompt: vi.fn(
      (_data: Record<string, unknown>, _token: string | null) =>
        jsonResponse({}),
    ),
    getSinglePrompt: vi.fn((id: string) =>
      jsonResponse({ content: `Text of ${id}`, updated_at: 'v1' }),
    ),
    updatePrompt: vi.fn(
      (_data: Record<string, unknown>, _token: string | null) =>
        jsonResponse({}),
    ),
    tools: null as unknown[] | null,
    models: [] as unknown[],
    defaultModelId: '',
    connections: [] as unknown[],
    catalog: [] as unknown[],
    deleteAgent: vi.fn(() => jsonResponse({})),
    updateAgent: vi.fn<
      (id: string, data: FormData, token: string | null) => Promise<unknown>
    >(() => jsonResponse({})),
    guardrailsProps: vi.fn(),
    detailsProps: vi.fn(),
    shareProps: vi.fn(),
    reconnect: vi.fn(),
    signInOptions: null as null | { onNavigate?: (to: string) => void },
    toolsCalls: [] as number[],
    fileUploadProps: null as null | { onUpload: (files: File[]) => void },
    addToolProps: null as null | {
      modalState: string;
      onToolsCreated: (ids: string[]) => void;
      onNavigate?: (to: string) => void;
    },
  };
});
const { jsonResponse } = mocks;

vi.mock('../connectors/SignInAgainNotice', () => ({
  default: () => null,
  useSignInAgain: (options: { onNavigate?: (to: string) => void }) => {
    mocks.signInOptions = options;
    return { reconnect: mocks.reconnect, modals: null };
  },
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(mockState),
  useDispatch: () => mocks.dispatch,
}));

// The drafter: its config (off unless a test turns it on) and its stream,
// which plays one script of events per turn.
const drafter = vi.hoisted(() => ({
  config: null as null | {
    enabled: boolean;
    model: { id: string; display_name: string } | null;
    reason: null;
  },
  // A promise is a turn whose events land when it resolves.
  scripts: [] as (unknown[] | Promise<unknown[]>)[],
  requests: [] as {
    recipe: string;
    messages: { role: string; content: string }[];
    context: {
      agent_id: string | null;
      step?: string | null;
      earlier?: string[];
      form: Record<string, unknown>;
    };
  }[],
}));
vi.mock('../drafter/useDrafterConfig', () => ({
  useDrafterConfig: () => drafter.config,
}));
vi.mock('../drafter/drafterApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../drafter/drafterApi')>()),
  streamDrafter: async (
    request: (typeof drafter.requests)[number],
    _token: string | null,
    onEvent: (event: unknown) => void,
  ) => {
    drafter.requests.push(JSON.parse(JSON.stringify(request)));
    (await (drafter.scripts.shift() ?? [{ type: 'end' }])).forEach(onEvent);
  },
}));

vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: () =>
      mocks.toolsCalls.push(1) &&
      jsonResponse({
        tools: mocks.tools ?? [
          {
            id: 'tool-1',
            name: 'remote_device',
            display_name: 'Laptop',
            config: { device_id: 'device-1' },
          },
        ],
      }),
    getAgentFolders: () => jsonResponse({ folders: [] }),
    getAgent: mocks.getAgent,
    getAgentDefaults: mocks.getAgentDefaults,
    createAgent: mocks.createAgent,
    updateAgent: mocks.updateAgent,
    deleteAgent: mocks.deleteAgent,
    createPrompt: mocks.createPrompt,
    updatePrompt: mocks.updatePrompt,
    getSinglePrompt: mocks.getSinglePrompt,
    getPrompts: () => jsonResponse([]),
  },
}));

vi.mock('../api/services/devicesService', () => ({
  default: {
    list: () =>
      Promise.resolve({
        devices: [{ id: 'device-1', last_seen_at: new Date().toISOString() }],
      }),
  },
}));

vi.mock('../api/services/connectorsService', () => ({
  default: {
    listConnections: () => Promise.resolve({ connections: mocks.connections }),
    getCatalog: () =>
      Promise.resolve({ success: true, connectors: mocks.catalog }),
  },
}));

vi.mock('../api/services/modelService', () => ({
  default: {
    getModels: () =>
      mocks.jsonResponse({
        models: mocks.models,
        default_model_id: mocks.defaultModelId,
      }),
    transformModels: (models: unknown[]) => models,
  },
}));

// The pickers render only their trigger here, plus each item's rich
// description so the device status pill can be checked.
vi.mock('../components/MultiSelectPopover', () => ({
  MultiSelectPopover: ({
    trigger,
    items,
    onToggle,
    title,
    searchPlaceholder,
    selectedFirst,
    footer,
    filters,
    emptyMessage,
    loneGroupHeading,
    onOpenChange,
  }: {
    trigger: React.ReactNode;
    items: MultiSelectPopoverItem[];
    onToggle: (id: string) => void;
    title?: string;
    searchPlaceholder?: string;
    selectedFirst?: boolean;
    footer?: React.ReactNode;
    filters?: React.ReactNode;
    emptyMessage?: string;
    loneGroupHeading?: boolean;
    onOpenChange?: (open: boolean) => void;
  }) => (
    <div
      data-testid="picker"
      data-title={title}
      data-search={searchPlaceholder}
      data-selected-first={selectedFirst ? 'true' : undefined}
      data-empty={emptyMessage}
      data-lone-group-heading={String(loneGroupHeading ?? true)}
    >
      {trigger}
      {/* A span, so the tests that count the picker's buttons skip it. */}
      <span data-testid="picker-open" onClick={() => onOpenChange?.(true)} />
      <div data-testid="picker-footer">{footer}</div>
      <div data-testid="picker-filters">{filters}</div>
      {items.map((item) => (
        <div
          key={item.id}
          data-group={item.group}
          data-item={item.id}
          data-description={item.description}
        >
          {item.descriptionNode}
          <button
            type="button"
            data-toggle={item.id}
            onClick={() => onToggle(item.id)}
          />
        </div>
      ))}
    </div>
  ),
}));

vi.mock('./AgentPreview', () => ({ default: () => null }));
vi.mock('./components/GuardrailsSection', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./components/GuardrailsSection')>()),
  default: (props: { disabled?: boolean }) => {
    mocks.guardrailsProps(props);
    return null;
  },
  guardrailsIncomplete: () => false,
}));
vi.mock('../upload/Upload', () => ({ default: () => null }));
vi.mock('../modals/AddToolModal', () => ({
  default: (props: {
    modalState: string;
    onToolsCreated: (ids: string[]) => void;
  }) => {
    mocks.addToolProps = props;
    return null;
  },
}));
vi.mock('../modals/AgentDetailsModal', () => ({
  default: (props: unknown) => {
    mocks.detailsProps(props);
    return null;
  },
}));
vi.mock('../teams/ShareToTeamModal', () => ({
  default: (props: unknown) => {
    mocks.shareProps(props);
    return null;
  },
}));
vi.mock('../modals/ConfirmationModal', () => ({
  default: ({
    modalState,
    handleSubmit,
    error,
  }: {
    modalState: string;
    handleSubmit: () => void | Promise<unknown>;
    error?: string;
  }) =>
    modalState === 'ACTIVE' ? (
      <>
        <button
          type="button"
          data-testid="confirm-delete"
          onClick={() => {
            const result = handleSubmit();
            // Mark it handled; the tests assert on it afterwards.
            if (result) result.catch(() => undefined);
            mocks.submitResult = result;
          }}
        >
          confirm
        </button>
        <p data-testid="confirm-error">{error}</p>
      </>
    ) : null,
}));
vi.mock('./components/SponsorConfirmModal', () => ({
  default: ({
    confirmation,
    onConfirm,
  }: {
    confirmation: { resources: { key: string; name: string }[] } | null;
    onConfirm: (keys: string[]) => void;
  }) =>
    confirmation ? (
      <button
        type="button"
        data-testid="confirm-sponsor"
        onClick={() => onConfirm(confirmation.resources.map((r) => r.key))}
      >
        {confirmation.resources.map((r) => r.name).join(',')}
      </button>
    ) : null,
}));
vi.mock('../navigation/SectionPills', () => ({
  default: () => <div data-testid="section-pills" />,
}));
vi.mock('../navigation/SectionPageHeader', () => ({
  CurrentSectionHeader: ({ title }: { title?: React.ReactNode }) =>
    title ? <h1>{title}</h1> : null,
}));
vi.mock('../components/FileUpload', () => ({
  FileUpload: (props: { onUpload: (files: File[]) => void }) => {
    mocks.fileUploadProps = props;
    return null;
  },
}));
vi.mock('../components/SourcesPopoverFooter', () => ({ default: () => null }));
vi.mock('../components/ToolIcon', () => ({ default: () => null }));

import NewAgent from './NewAgent';

// The router's navigate and the location's state, for browser Back.
const probe = {
  navigate: null as null | ((delta: number) => void),
  state: null as unknown,
};
function RouterProbe() {
  probe.navigate = useNavigate();
  probe.state = useLocation().state;
  return null;
}

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const setNativeValue = (
  el: HTMLInputElement | HTMLTextAreaElement,
  value: string,
) => {
  const proto =
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
};

describe('NewAgent form', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    mocks.dispatch.mockClear();
    mocks.getAgent.mockClear();
    mocks.createAgent.mockClear();
    mocks.updateAgent.mockReset();
    mocks.updateAgent.mockImplementation(() => jsonResponse({}));
    mocks.tools = null;
    mocks.models = [];
    mocks.defaultModelId = '';
    mocks.connections = [];
    mocks.catalog = [];
    media.isMobile = false;
    media.isDesktop = true;
  });

  const render = async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <NewAgent mode="new" />
        </MemoryRouter>,
      );
    });
  };

  const buttonByText = (text: string) =>
    Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes(text),
    )!;

  it('starts a new agent from the default guardrails for new agents', async () => {
    const defaults = {
      enabled: true,
      mode: 'monitor_only',
      fail_open: true,
      timeout_ms: 2000,
      block_message: 'No',
      controls: [
        {
          check: 'injection_model',
          stage: 'input',
          action: 'flag',
          enabled: true,
          settings: { threshold: 0.9, flag_threshold: 0.5 },
        },
      ],
    };
    mocks.getAgentDefaults.mockImplementationOnce(() =>
      jsonResponse({ success: true, guardrails: defaults }),
    );
    await render();
    expect(mocks.getAgentDefaults).toHaveBeenCalled();
    expect(mocks.guardrailsProps.mock.calls.at(-1)?.[0].value).toEqual(
      defaults,
    );
  });

  // Decision 63 (3): every field, picker and button in the form is 42px.
  it('renders the name field as a default-size square Input', async () => {
    await render();
    const name = container.querySelector<HTMLInputElement>(
      'input[placeholder="agents.form.placeholders.agentName"]',
    )!;
    expect(name.getAttribute('data-slot')).toBe('input');
    expect(name.getAttribute('data-size')).toBe('default');
    // S8: form controls are square; only the page chrome is pill.
    expect(name.getAttribute('data-shape')).toBe('default');
  });

  it('renders the model Select triggers as square field controls', async () => {
    await render();
    const triggers = Array.from(
      container.querySelectorAll('[data-slot="select-trigger"]'),
    );
    expect(triggers.length).toBeGreaterThan(0);
    for (const trigger of triggers) {
      expect(trigger.getAttribute('data-size')).toBe('field');
      expect(trigger.getAttribute('data-shape')).toBe('default');
    }
  });

  // The prompt is picked like a tool or a source: a picker whose footer
  // goes to the Prompts page or adds one, no Add button beside it; a row's
  // only action opens the prompt (Edit, or View for one the role can't).
  it('picks the prompt from a Combobox with a Go to Prompts footer', async () => {
    mockState.preference.prompts = [
      { id: 'default', name: 'default', type: 'public' },
      { id: 'p1', name: 'Tone', type: 'private', access: 'owner' },
    ] as never[];
    try {
      await render();
      const trigger = container.querySelector<HTMLButtonElement>(
        '[data-slot="combobox-trigger"]',
      )!;
      expect(trigger.textContent).toContain('default');
      expect(
        trigger.closest('[data-slot="form-field"]')?.querySelector('label')
          ?.textContent,
      ).toBe('agents.form.sections.prompt');
      expect(buttonByText('agents.form.buttons.add')).toBeUndefined();
      await act(async () => {
        trigger.dispatchEvent(
          new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
        );
        trigger.click();
      });
      const list = document.body.querySelector('[cmdk-list]')!;
      const rows = Array.from(list.querySelectorAll('[cmdk-item]'));
      expect(rows.map((row) => row.getAttribute('data-value'))).toEqual([
        'default',
        'p1',
      ]);
      // Edit or View only: duplicate, share and delete are on the page.
      expect(
        Array.from(list.querySelectorAll('button')).map((button) =>
          button.getAttribute('aria-label'),
        ),
      ).toEqual(['settings.prompts.viewNamed', 'settings.prompts.editNamed']);
      // Half width on a wide screen, like Default model.
      expect(
        trigger.closest('[data-slot="form-field"]')!.parentElement!
          .parentElement!.className,
      ).not.toContain('col-span-2');
      const link = Array.from(document.body.querySelectorAll('a')).find(
        (a) => a.textContent === 'settings.prompts.manage',
      )!;
      expect(link.getAttribute('href')).toBe('/settings/prompts');
      const add = Array.from(document.body.querySelectorAll('button')).find(
        (b) => b.textContent === 'settings.prompts.addPrompt',
      )!;
      expect(add.getAttribute('data-variant')).toBe('outline-primary');
      await act(async () => (rows[1] as HTMLElement).click());
      expect(trigger.textContent).toContain('Tone');
    } finally {
      mockState.preference.prompts = [];
    }
  });

  const openPromptPicker = async () => {
    const trigger = container.querySelector<HTMLButtonElement>(
      '[data-slot="combobox-trigger"]',
    )!;
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
  };
  const promptRow = (value: string) =>
    document.body.querySelector<HTMLElement>(
      `[cmdk-item][data-value="${value}"]`,
    )!;
  const promptLine = (value: string) =>
    promptRow(value)?.querySelector('[data-slot="combobox-description"]')
      ?.textContent;

  // W10: the Prompt picker has the other pickers' chrome: a title, one line
  // per row that says what the prompt is, and a check on the picked row.
  it("gives the prompt picker the pickers' title and a line per row", async () => {
    mockState.preference.prompts = [
      { id: 'default', name: 'default', type: 'public' },
      { id: 'creative', name: 'creative', type: 'public' },
      {
        id: 'p1',
        name: 'Tone',
        type: 'private',
        access: 'owner',
        preview: 'You are terse.',
      },
      {
        id: 'p2',
        name: 'Escalations',
        type: 'team',
        access: 'viewer',
        preview: 'Escalate politely.',
      },
    ] as never[];
    try {
      await render();
      await openPromptPicker();
      const content = document.body.querySelector(
        '[data-slot="popover-content"]',
      )!;
      expect(content.querySelector('h3')?.textContent).toBe(
        'agents.form.sections.prompt',
      );
      expect(promptLine('default')).toBe('settings.prompts.presets.default');
      expect(promptLine('creative')).toBe('settings.prompts.presets.creative');
      expect(promptLine('p1')).toBe('You are terse.');
      expect(promptLine('p2')).toBe('Escalate politely.');
      expect(promptRow('default').querySelector('svg.lucide-check')).not.toBe(
        null,
      );
      // Four prompts fit: no kind track.
      expect(content.querySelector('[data-slot="combobox-filters"]')).toBe(
        null,
      );
    } finally {
      mockState.preference.prompts = [];
    }
  });

  // A kind filter that hides the picked prompt must not bring back the name
  // of the prompt the agent was saved with.
  it('names the picked prompt from the full list while a kind hides it', async () => {
    mockState.preference.prompts = [
      { id: 'default', name: 'default', type: 'public' },
      { id: 'creative', name: 'creative', type: 'public' },
      { id: 'strict', name: 'strict', type: 'public' },
      ...Array.from({ length: 7 }, (_, i) => ({
        id: `own-${i}`,
        name: `Mine ${i}`,
        type: 'private',
        access: 'owner',
      })),
      { id: 'team-1', name: 'Theirs', type: 'team', access: 'viewer' },
    ] as never[];
    try {
      await renderEdit({ prompt_id: 'own-0', prompt_name: 'Mine 0' });
      const trigger = container.querySelector<HTMLButtonElement>(
        '[data-slot="combobox-trigger"]',
      )!;
      await openPromptPicker();
      await act(async () => promptRow('team-1')!.click());
      expect(trigger.textContent).toContain('Theirs');
      await openPromptPicker();
      const kinds = Array.from(
        document.body.querySelectorAll<HTMLButtonElement>(
          '[data-slot="combobox-filters"] [data-slot="toggle-group-item"]',
        ),
      );
      // Yours: the picked teammate's prompt is filtered out.
      await act(async () => kinds[2].click());
      expect(trigger.textContent).toContain('Theirs');
      expect(trigger.textContent).not.toContain('Mine 0');
    } finally {
      mockState.preference.prompts = [];
    }
  });

  it('filters the prompt picker by kind past ten prompts', async () => {
    mockState.preference.prompts = [
      { id: 'default', name: 'default', type: 'public' },
      { id: 'creative', name: 'creative', type: 'public' },
      { id: 'strict', name: 'strict', type: 'public' },
      ...Array.from({ length: 7 }, (_, i) => ({
        id: `own-${i}`,
        name: `Mine ${i}`,
        type: 'private',
        access: 'owner',
      })),
      { id: 'team-1', name: 'Theirs', type: 'team', access: 'viewer' },
    ] as never[];
    try {
      await render();
      await openPromptPicker();
      const track = document.body.querySelector(
        '[data-slot="combobox-filters"]',
      )!;
      const kinds = Array.from(
        track.querySelectorAll<HTMLButtonElement>(
          '[data-slot="toggle-group-item"]',
        ),
      );
      expect(kinds.map((kind) => kind.firstChild?.textContent)).toEqual([
        'settings.prompts.filters.all',
        'settings.prompts.sections.included',
        'settings.prompts.sections.yours',
        // Short, as on the Prompts page's track.
        'settings.prompts.kinds.shared',
      ]);
      await act(async () => kinds[2].click());
      const rows = Array.from(
        document.body.querySelectorAll('[cmdk-item]'),
      ).map((row) => row.getAttribute('data-value'));
      expect(rows).toHaveLength(7);
      expect(rows.every((id) => id?.startsWith('own-'))).toBe(true);
    } finally {
      mockState.preference.prompts = [];
    }
  });

  it('opens the prompt picker as a bottom sheet on a phone', async () => {
    media.isMobile = true;
    media.isDesktop = false;
    mockState.preference.prompts = [
      { id: 'default', name: 'default', type: 'public' },
      { id: 'strict', name: 'strict', type: 'public' },
    ] as never[];
    try {
      await render();
      await act(async () =>
        container
          .querySelector<HTMLButtonElement>('[data-slot="combobox-trigger"]')!
          .click(),
      );
      const sheet = document.body.querySelector<HTMLElement>(
        '[data-slot="sheet-content"]',
      )!;
      expect(sheet.dataset.side).toBe('bottom');
      expect(sheet.querySelector('[data-slot="sheet-handle"]')).not.toBe(null);
      expect(sheet.querySelector('h3')?.textContent).toBe(
        'agents.form.sections.prompt',
      );
      await act(async () => promptRow('strict').click());
      expect(document.body.querySelector('[data-slot="sheet-content"]')).toBe(
        null,
      );
      expect(
        container.querySelector('[data-slot="combobox-trigger"]')?.textContent,
      ).toContain('strict');
    } finally {
      mockState.preference.prompts = [];
    }
  });

  it('renders the token and request limits as default-size square Inputs', async () => {
    await render();
    await act(async () =>
      buttonByText('agents.form.sections.advanced').click(),
    );
    for (const key of ['enterTokenLimit', 'enterRequestLimit']) {
      const field = container.querySelector(
        `input[placeholder="agents.form.placeholders.${key}"]`,
      )!;
      expect(field.getAttribute('data-size')).toBe('default');
      expect(field.getAttribute('data-shape')).toBe('default');
    }
  });

  // A1a: three grouped sections instead of six one-field panels.
  it('groups the form into Basics, Knowledge and behaviour, and Model', async () => {
    await render();
    const titles = Array.from(
      container.querySelectorAll('[data-slot="section-header"] > h2'),
    ).map((h) => h.textContent);
    expect(titles).toEqual([
      'agents.form.sections.basics',
      'agents.form.sections.knowledge',
      'agents.form.sections.model',
    ]);
    const basics = Array.from(
      container.querySelectorAll('[data-slot="section-header"]'),
    ).find((h) => h.textContent === 'agents.form.sections.basics')!;
    expect(basics.parentElement!.className.split(' ')).toEqual(
      expect.arrayContaining(['flex', 'flex-col', 'gap-5']),
    );
  });

  // On a phone the avatar sits beside Name and Description spans the row;
  // from sm the avatar spans both rows beside the fields.
  it('lays Basics out as avatar beside Name, Description full width on a phone', async () => {
    await render();
    const name = container.querySelector(
      'input[placeholder="agents.form.placeholders.agentName"]',
    )!;
    const grid = name.closest('.grid')!;
    expect(grid.className).toContain('grid-cols-[auto_1fr]');
    const description = container
      .querySelector(
        'textarea[placeholder="agents.form.placeholders.describeAgent"]',
      )!
      // The grid cell is the field's drafted-marker wrapper.
      .closest('[data-slot="drafted-field"]')!;
    expect(description.className).toContain('col-span-2');
    expect(description.className).toContain('sm:col-start-2');
  });

  it('groups tools like the chat and the Tools page: included, added, each service, custom', async () => {
    mocks.tools = [
      { id: 'custom', name: 'api_tool', display_name: 'My API' },
      { id: 'notes', name: 'notes', display_name: 'Notes' },
      {
        id: 'linear',
        name: 'mcp_tool',
        display_name: 'Linear',
        connection_id: 'c-lin',
      },
      { id: 'memory', name: 'memory', display_name: 'Memory', builtin: true },
      {
        id: 'notion',
        name: 'mcp_tool',
        display_name: 'Notion',
        connection_id: 'c-not',
      },
      {
        id: 'reader',
        name: 'read_webpage',
        display_name: 'Reader',
        default: true,
      },
    ];
    mocks.connections = [
      { id: 'c-lin', name: 'Linear', account_label: 'a@x', icon: 'linear' },
      { id: 'c-not', name: 'Notion', account_label: 'b@x', icon: 'notion' },
    ];
    await render();
    const groups = Array.from(
      container.querySelectorAll('[data-testid="picker"] [data-group]'),
    ).map((item) => item.getAttribute('data-group'));
    const order = groups.filter((g, i) => groups.indexOf(g) === i);
    expect(order).toEqual([
      'included',
      'added',
      'service:Linear',
      'service:Notion',
      'custom',
    ]);
    // The account is the row's line, not part of the heading.
    expect(
      container
        .querySelector('[data-item="linear"]')
        ?.getAttribute('data-description'),
    ).toBe('a@x');
  });

  // A teammate's connection is never in the caller's list; its tool still
  // belongs with the services, named from the catalog.
  it("groups a teammate's connected tool under its service, before custom", async () => {
    mocks.tools = [
      { id: 'custom', name: 'api_tool', display_name: 'My API' },
      {
        id: 'shared-tg',
        name: 'telegram',
        displayName: 'Telegram',
        connection_id: 'owner-conn',
        access: 'viewer',
        allowed_actions: ['use', 'use_in_own'],
      },
    ];
    mocks.catalog = [
      {
        key: 'telegram',
        name: 'Telegram',
        icon: 'tool_telegram',
        publisher: 'built_in',
        tool_templates: ['telegram'],
      },
    ];
    await render();
    const groups = Array.from(
      container.querySelectorAll('[data-testid="picker"] [data-group]'),
    ).map((item) => item.getAttribute('data-group'));
    expect(groups).toEqual(['service:Telegram', 'custom']);
  });

  const renderEdit = async (agent: Record<string, unknown>) => {
    mocks.getAgent.mockImplementationOnce(() =>
      jsonResponse({
        id: 'agent-1',
        name: 'Shared',
        description: 'd',
        status: 'published',
        agent_type: 'classic',
        prompt_id: 'default',
        access: 'editor',
        allowed_actions: ['edit', 'view'],
        ...agent,
      }),
    );
    await act(async () => {
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
  };

  // The route guard sends a workflow on to its editor when its record says
  // so; the form still never takes one it reads itself.
  it('hands a workflow agent it loads on to the workflow editor', async () => {
    mocks.getAgent.mockImplementationOnce(() =>
      jsonResponse({
        id: 'agent-1',
        name: 'Flow',
        description: 'd',
        status: 'published',
        agent_type: 'workflow',
        workflow_id: 'wf-1',
        allowed_actions: ['edit', 'view'],
      }),
    );
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/edit/agent-1']}>
          <Routes>
            <Route
              path="/agents/manage/edit/:agentId"
              element={<NewAgent mode="edit" />}
            />
            <Route
              path="/agents/manage/workflow/edit/:agentId"
              element={<div data-testid="workflow-builder" />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    await act(async () => undefined);
    expect(
      container.querySelector('[data-testid="workflow-builder"]'),
    ).not.toBeNull();
    expect(
      container.querySelector(
        'input[placeholder="agents.form.placeholders.agentName"]',
      ),
    ).toBeNull();
  });

  const goToTools = () =>
    container.querySelector<HTMLAnchorElement>(
      '[data-title="settings.tools.label"] [data-testid="picker-footer"] a',
    )!;

  const asked = () =>
    // This file stubs ConfirmationModal as its confirm button.
    container.querySelector('[data-testid="confirm-delete"]') !== null;
  const typeName = async (value: string) =>
    act(async () =>
      setNativeValue(
        container.querySelector<HTMLInputElement>(
          'input[placeholder="agents.form.placeholders.agentName"]',
        )!,
        value,
      ),
    );

  it('asks before Go to Tools leaves unsaved changes', async () => {
    await render();
    await typeName('Support bot');
    await act(async () => goToTools().click());
    expect(asked()).toBe(true);
  });

  // The defaults a new agent starts from (the instance's model, the admin's
  // guardrails) are not changes of the user's.
  it('lets Go to Tools go from an untouched new agent', async () => {
    mocks.models = [{ id: 'm1', display_name: 'Model one', provider: 'x' }];
    mocks.defaultModelId = 'm1';
    mocks.getAgentDefaults.mockImplementationOnce(() =>
      jsonResponse({ success: true, guardrails: { enabled: true } }),
    );
    await render();
    await act(async () => undefined);
    expect(buttonByText('agents.form.buttons.cancel')).toBeUndefined();
    await act(async () => goToTools().click());
    expect(asked()).toBe(false);
  });

  it('reads a new agent as saved once its draft is saved', async () => {
    mocks.createAgent.mockImplementationOnce(() =>
      jsonResponse({ id: 'agent-9' }),
    );
    await render();
    await typeName('Support bot');
    await act(async () =>
      buttonByText('agents.form.buttons.saveDraft').click(),
    );
    expect(mocks.createAgent).toHaveBeenCalledTimes(1);
    await act(async () => goToTools().click());
    expect(asked()).toBe(false);
  });

  it('uploads a picked avatar once, not again with the next draft save', async () => {
    mocks.createAgent.mockImplementationOnce(() =>
      jsonResponse({ id: 'agent-9', image: '/img/a.png' }),
    );
    mocks.updateAgent.mockImplementation(() => jsonResponse({ id: 'agent-9' }));
    await render();
    await typeName('Support bot');
    const file = new File(['x'], 'a.png', { type: 'image/png' });
    await act(async () => mocks.fileUploadProps!.onUpload([file]));
    const saveDraft = () =>
      act(async () => buttonByText('agents.form.buttons.saveDraft').click());
    await saveDraft();
    const created = (
      mocks.createAgent.mock.calls.at(-1) as unknown as [FormData]
    )[0];
    expect(created.get('image')).toBe(file);
    await typeName('Support bot 2');
    await saveDraft();
    const updated = mocks.updateAgent.mock.calls.at(-1)![1];
    expect(updated.get('image')).toBeNull();
  });

  // The server starts a new agent from the admin's default guardrails; when
  // the form never got them (their read failed, or came after the save), an
  // allowlist change must save onto the server's config, not drop them.
  it("saves an allowlist change on a just-created agent onto the server's config", async () => {
    mocks.getAgentDefaults.mockImplementationOnce(() =>
      jsonResponse({}, false),
    );
    mocks.createAgent.mockImplementationOnce(() =>
      jsonResponse({ id: 'agent-9' }),
    );
    await render();
    await typeName('Support bot');
    await act(async () =>
      buttonByText('agents.form.buttons.saveDraft').click(),
    );
    expect(mocks.createAgent).toHaveBeenCalledTimes(1);
    const guardrails = { controls: [{ id: 'pii' }] };
    mocks.getAgent.mockImplementationOnce(() =>
      jsonResponse({ id: 'agent-9', config: { guardrails } }),
    );
    const details = mocks.detailsProps.mock.calls.at(-1)![0] as {
      getSavedConfig: () => unknown;
    };
    await expect(Promise.resolve(details.getSavedConfig())).resolves.toEqual({
      guardrails,
    });
    expect(mocks.getAgent).toHaveBeenCalledWith('agent-9', null);
  });

  it('keeps Publish on for a saved draft with no new changes', async () => {
    mocks.getAgent.mockImplementationOnce(() =>
      jsonResponse({
        id: 'agent-1',
        name: 'Draft bot',
        description: 'd',
        status: 'draft',
        agent_type: 'classic',
        prompt_id: 'default',
      }),
    );
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/edit/agent-1']}>
          <Routes>
            <Route
              path="/agents/edit/:agentId"
              element={<NewAgent mode="draft" />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    expect(buttonByText('agents.form.buttons.publish').disabled).toBe(false);
    await act(async () => goToTools().click());
    expect(asked()).toBe(false);
  });

  // Add tool's ways out (Browse all, the API tool editor, Try it in chat)
  // come back through the builder.
  it("asks before Add tool's Browse all leaves unsaved changes", async () => {
    await render();
    await typeName('Support bot');
    await act(async () =>
      mocks.addToolProps!.onNavigate!('/settings/connectors'),
    );
    expect(asked()).toBe(true);
  });

  // A connection that can't sign in again in place opens its connector
  // page: an exit like any other.
  it('asks before a reconnect leaves for the connector page', async () => {
    await render();
    await typeName('Support bot');
    await act(async () =>
      mocks.signInOptions!.onNavigate!('/settings/connectors?connector=x'),
    );
    expect(asked()).toBe(true);
  });

  // Save draft and Publish both create a new agent: only one may be out.
  it('runs one save at a time across Save draft and Publish', async () => {
    let finish: (value: unknown) => void = () => undefined;
    mocks.createAgent.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }) as never,
    );
    await render();
    await typeName('Support bot');
    await act(async () =>
      setNativeValue(
        container.querySelector<HTMLTextAreaElement>(
          'textarea[placeholder="agents.form.placeholders.describeAgent"]',
        )!,
        'Helps',
      ),
    );
    await act(async () =>
      buttonByText('agents.form.buttons.saveDraft').click(),
    );
    const publish = buttonByText('agents.form.buttons.publish');
    expect(publish.disabled).toBe(true);
    await act(async () => publish.click());
    expect(mocks.createAgent).toHaveBeenCalledTimes(1);
    await act(async () =>
      finish({ ok: true, json: () => Promise.resolve({ id: 'agent-9' }) }),
    );
  });

  // A team editor's save carries the stamp it loaded, so the server can
  // refuse it when someone saved in between; the edits stay.
  it('sends the loaded stamp and keeps the edits when the save is stale', async () => {
    mocks.updateAgent.mockImplementationOnce(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            success: false,
            message: 'Agent was modified by someone else',
            code: 'stale_write',
          }),
          { status: 409, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    );
    await renderEdit({ updated_at: '2026-10-30T10:00:00.123456+00:00' });
    await typeName('Renamed');
    await act(async () => buttonByText('agents.form.buttons.save').click());
    const form = mocks.updateAgent.mock.calls.at(-1)![1];
    expect(form.get('expected_updated_at')).toBe(
      '2026-10-30T10:00:00.123456+00:00',
    );
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'agents.form.errors.staleWrite',
    );
    expect(
      container.querySelector<HTMLInputElement>(
        'input[placeholder="agents.form.placeholders.agentName"]',
      )!.value,
    ).toBe('Renamed');
  });

  it('sends the stamp the last save answered with', async () => {
    mocks.updateAgent.mockImplementation(() =>
      jsonResponse({ success: true, id: 'agent-1', updated_at: 'stamp-2' }),
    );
    await renderEdit({ updated_at: 'stamp-1' });
    await typeName('Once');
    await act(async () => buttonByText('agents.form.buttons.save').click());
    await typeName('Twice');
    await act(async () => buttonByText('agents.form.buttons.save').click());
    const form = mocks.updateAgent.mock.calls.at(-1)![1];
    expect(form.get('expected_updated_at')).toBe('stamp-2');
  });

  it('sends the stamp an allowlist save answered with', async () => {
    mocks.updateAgent.mockImplementation(() =>
      jsonResponse({ success: true, id: 'agent-1', updated_at: 'stamp-3' }),
    );
    await renderEdit({ updated_at: 'stamp-1' });
    const details = () =>
      mocks.detailsProps.mock.calls.at(-1)![0] as {
        onConfigChange: (
          config: Record<string, unknown>,
          updatedAt?: string,
        ) => void;
      };
    await act(async () =>
      details().onConfigChange({ api_write_allowlist: ['t:a'] }, 'stamp-2'),
    );
    await typeName('Renamed');
    await act(async () => buttonByText('agents.form.buttons.save').click());
    const form = mocks.updateAgent.mock.calls.at(-1)![1];
    expect(form.get('expected_updated_at')).toBe('stamp-2');
  });

  it('lets Go to Tools go when the agent is saved', async () => {
    await renderEdit({});
    await act(async () => goToTools().click());
    expect(
      container.querySelector('[data-testid="confirm-delete"]'),
    ).toBeNull();
  });

  // The server lists tool_details in its own order and leaves out deleted
  // tools: an untouched agent still reads as saved.
  it('reads an agent as saved when its tool details come back reordered or short', async () => {
    await renderEdit({
      tools: ['t-a', 't-b', 't-gone'],
      tool_details: [
        { id: 't-b', name: 'jira', display_name: 'Jira' },
        { id: 't-a', name: 'api_tool', display_name: 'My API' },
      ],
    });
    expect(buttonByText('agents.form.buttons.cancel')).toBeUndefined();
    await act(async () => goToTools().click());
    expect(asked()).toBe(false);
  });

  // An editor doesn't list the owner's private tools, but must still be able
  // to take one off the agent.
  it("adds a remove-only row for an attached tool the editor can't list", async () => {
    mocks.tools = [{ id: 'mine', name: 'api_tool', display_name: 'My API' }];
    await renderEdit({
      tools: ['owners'],
      tool_details: [
        { id: 'owners', name: 'jira', display_name: 'Owner Jira' },
      ],
    });
    const toolPicker = Array.from(
      container.querySelectorAll('[data-testid="picker"]'),
    ).find((picker) => picker.textContent?.includes('Owner Jira'))!;
    const groups = Array.from(toolPicker.querySelectorAll('[data-group]')).map(
      (item) => item.getAttribute('data-group'),
    );
    // No "On this agent" group: it is on the agent, so the picker's
    // Selected group holds it when it opens.
    expect(groups).toEqual(['added', 'custom']);
    expect(
      container
        .querySelector('[data-item="owners"]')
        ?.getAttribute('data-description'),
    ).toBe('agents.form.toolsPopup.attachedHint');
  });

  // The sponsor confirmation asks before anything runs with an editor's
  // access, so the form keeps no attach note; who added what is on the
  // picker rows.
  it('marks who added a sponsored tool and source in the pickers, with no note', async () => {
    mocks.tools = [{ id: 'mine', name: 'api_tool', display_name: 'My API' }];
    await renderEdit({
      tools: ['mine'],
      sources: ['s1'],
      shared: true,
      resource_sponsors: [
        {
          type: 'tool',
          id: 'mine',
          user_id: 'bob',
          label: 'bob@example.com',
          active: true,
        },
        { type: 'source', id: 's1', user_id: null, label: null, active: true },
      ],
    });
    expect(
      container
        .querySelector('[data-item="mine"]')
        ?.getAttribute('data-description'),
    ).toBe('agents.form.sponsors.addedBy');
    expect(
      container
        .querySelector('[data-item="s1"]')
        ?.getAttribute('data-description'),
    ).toBe('agents.form.sponsors.addedByOther');
    expect(container.textContent).not.toContain('agents.form.sponsors.attach');
    expect(container.textContent).not.toContain('publicLinkNote');
    expect(
      container.querySelector(
        '[data-slot="alert"]:not([data-testid="origins-read-only"])',
      ),
    ).toBeNull();
  });

  // A picker row has one line: who added a tool joins it, after the line.
  it("folds who added a tool into the row's one line", async () => {
    mocks.tools = [
      {
        id: 'crm',
        name: 'api_tool',
        display_name: 'CRM',
        description: 'Calls the CRM',
      },
      {
        id: 'linear',
        name: 'mcp_tool',
        display_name: 'Linear',
        connection_id: 'c-lin',
      },
    ];
    mocks.connections = [
      {
        id: 'c-lin',
        name: 'Linear',
        account_label: 'a@x',
        icon: 'linear',
        status: 'reconnect_needed',
      },
    ];
    const sponsor = (id: string) => ({
      type: 'tool',
      id,
      user_id: 'bob',
      label: 'bob@example.com',
      active: true,
    });
    await renderEdit({
      tools: ['crm', 'linear'],
      shared: true,
      resource_sponsors: [sponsor('crm'), sponsor('linear')],
    });
    expect(
      container
        .querySelector('[data-item="crm"]')
        ?.getAttribute('data-description'),
    ).toBe('Calls the CRM · agents.form.sponsors.addedBy');
    // A row with a status badge keeps the badge above its one line.
    const linear = container.querySelector('[data-item="linear"]')!;
    expect(linear.querySelector('[data-slot="badge"]')).not.toBe(null);
    const lines = Array.from(linear.querySelectorAll('p')).map(
      (p) => p.textContent,
    );
    expect(lines).toEqual(['a@x · agents.form.sponsors.addedBy']);
  });

  // The picked prompt's mark is a hint under its picker, seen while closed.
  it('marks a sponsored prompt under its picker', async () => {
    await renderEdit({
      prompt_id: 'p1',
      prompt_name: 'Tone',
      resource_sponsors: [
        {
          type: 'prompt',
          id: 'p1',
          user_id: 'bob',
          label: 'bob@example.com',
          active: true,
        },
      ],
    });
    const hint = Array.from(container.querySelectorAll('p')).find(
      (p) => p.textContent === 'agents.form.sponsors.addedBy',
    );
    expect(hint?.className).toContain('text-muted-foreground');
    expect(hint?.className).toContain('text-xs');
  });

  // F4: one word for the state, as a warning Badge like the device pill.
  it('marks a tool whose account needs signing in with a Reconnect badge', async () => {
    mocks.tools = [
      {
        id: 'linear',
        name: 'mcp_tool',
        display_name: 'Linear',
        connection_id: 'c-lin',
      },
    ];
    mocks.connections = [
      {
        id: 'c-lin',
        name: 'Linear',
        account_label: 'a@x',
        icon: 'linear',
        status: 'reconnect_needed',
      },
    ];
    await render();
    const badge = container.querySelector(
      '[data-item="linear"] [data-slot="badge"]',
    );
    expect(badge?.getAttribute('data-variant')).toBe('warning');
    expect(badge?.textContent).toBe('settings.connectors.status.reconnect');
    expect(
      container.querySelector('[data-item="linear"] p.text-warning'),
    ).toBeNull();
  });

  it('asks before sponsoring and retries the save with the confirmation', async () => {
    mocks.updateAgent.mockImplementationOnce(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            success: false,
            code: 'sponsor_confirmation_required',
            message: 'confirm',
            resources: [
              { key: 'tool:t1', type: 'tool', id: 't1', name: 'Jira' },
            ],
            audience: {
              teams: ['Support'],
              api_key: true,
              public_link: false,
              webhook: false,
            },
          }),
          { status: 409 },
        ),
      ),
    );
    await renderEdit({});
    const name = container.querySelector<HTMLInputElement>(
      'input[placeholder="agents.form.placeholders.agentName"]',
    )!;
    await act(async () => setNativeValue(name, 'Renamed'));
    await act(async () => buttonByText('agents.form.buttons.save').click());
    const confirm = container.querySelector<HTMLButtonElement>(
      '[data-testid="confirm-sponsor"]',
    )!;
    expect(confirm.textContent).toBe('Jira');
    // The refusal is a question, not an error.
    expect(container.querySelector('[data-variant="destructive"]')).toBeNull();
    expect(mocks.updateAgent).toHaveBeenCalledTimes(1);
    const first = mocks.updateAgent.mock.calls[0][1];
    expect(first.get('confirm_sponsor')).toBeNull();

    await act(async () => confirm.click());
    expect(mocks.updateAgent).toHaveBeenCalledTimes(2);
    const retried = mocks.updateAgent.mock.calls[1][1];
    expect(JSON.parse(retried.get('confirm_sponsor') as string)).toEqual([
      'tool:t1',
    ]);
    expect(
      container.querySelector('[data-testid="confirm-sponsor"]'),
    ).toBeNull();
  });

  const rename = async (value: string) => {
    const name = container.querySelector<HTMLInputElement>(
      'input[placeholder="agents.form.placeholders.agentName"]',
    )!;
    await act(async () => setNativeValue(name, value));
  };

  it('drops the remove-only row once the removal is saved', async () => {
    mocks.tools = [{ id: 'mine', name: 'api_tool', display_name: 'My API' }];
    await renderEdit({
      tools: ['owners'],
      tool_details: [
        { id: 'owners', name: 'jira', display_name: 'Owner Jira' },
      ],
    });
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-toggle="owners"]')!
        .click(),
    );
    // Still listed until saved, so it can be put back.
    expect(container.querySelector('[data-item="owners"]')).not.toBeNull();
    await act(async () => buttonByText('agents.form.buttons.save').click());
    expect(mocks.updateAgent).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[data-item="owners"]')).toBeNull();
  });

  const stoppedTool = {
    key: 'tool:t1',
    type: 'tool',
    id: 't1',
    name: 'Jira',
    state: 'stopped',
    reason: 'sponsor_cannot_edit_agent',
    sponsor: { user_id: 'bob', label: 'bob@example.com' },
    can_confirm: true,
  };
  const withStoppedTool = (item: Record<string, unknown> = {}) => ({
    tools: ['t1'],
    tool_details: [{ id: 't1', name: 'jira', display_name: 'Jira' }],
    resource_states: [{ ...stoppedTool, ...item }],
    sponsor_audience: {
      teams: ['Sales'],
      api_key: false,
      public_link: false,
      webhook: false,
    },
  });

  it('asks before taking over a stopped item and sends it with the next save', async () => {
    await renderEdit(withStoppedTool());
    const save = buttonByText('agents.form.buttons.save');
    expect(save.disabled).toBe(true);
    await act(async () =>
      buttonByText('agents.form.sponsors.takeOver').click(),
    );
    // Nothing is taken over until the reader agrees in the dialog.
    expect(save.disabled).toBe(true);
    const confirm = container.querySelector<HTMLButtonElement>(
      '[data-testid="confirm-sponsor"]',
    )!;
    expect(confirm.textContent).toBe('Jira');
    await act(async () => confirm.click());
    expect(container.textContent).toContain(
      'agents.form.sponsors.takeOverPending',
    );
    expect(save.disabled).toBe(false);
    await act(async () => save.click());
    const sent = mocks.updateAgent.mock.calls[0][1];
    expect(JSON.parse(sent.get('confirm_sponsor') as string)).toEqual([
      'tool:t1',
    ]);
    // The saved agent is fetched again for its fresh details.
    expect(mocks.getAgent).toHaveBeenCalledTimes(2);
  });

  const openAdvanced = async () => {
    const trigger = buttonByText('agents.form.sections.advanced');
    if (trigger.getAttribute('aria-expanded') !== 'true') {
      await act(async () => trigger.click());
    }
  };
  const limitInput = (key: 'contextLimitTokens' | 'historyLimitTokens') =>
    container.querySelector<HTMLInputElement>(
      `input[aria-label="agents.form.advanced.${key}"]`,
    )!;
  // A row's Switch, found through its label's `for`.
  const limitSwitch = (key: 'contextLimit' | 'historyLimit') => {
    const label = Array.from(container.querySelectorAll('label')).find(
      (el) => el.textContent === `agents.form.advanced.${key}`,
    )!;
    return document.getElementById(label.htmlFor) as HTMLButtonElement;
  };
  const sentConfig = () =>
    JSON.parse(mocks.updateAgent.mock.calls[0][1].get('config') as string);
  const withModel = (contextWindow: number) => {
    mocks.models = [
      { id: 'm1', display_name: 'Model One', context_window: contextWindow },
    ];
    return { models: ['m1'], default_model_id: 'm1' };
  };

  it("switches the context limit on and saves it in the agent's config", async () => {
    await renderEdit({
      allowed_actions: ['edit', 'view', 'edit_policy'],
      config: { api_write_allowlist: ['t:a'] },
      ...withModel(1_000_000),
    });
    await openAdvanced();
    expect(limitSwitch('contextLimit').getAttribute('aria-checked')).toBe(
      'false',
    );
    expect(limitInput('contextLimitTokens').disabled).toBe(true);
    await act(async () => limitSwitch('contextLimit').click());
    // Switched on, it starts from a value the model's window allows.
    expect(limitInput('contextLimitTokens').value).toBe('100000');
    await act(async () =>
      setNativeValue(limitInput('contextLimitTokens'), '32000'),
    );
    await act(async () => buttonByText('agents.form.buttons.save').click());
    // The rest of the config rides along: a config save replaces it whole.
    expect(sentConfig()).toMatchObject({
      api_write_allowlist: ['t:a'],
      context_window_limit: 32000,
    });
  });

  it("notes a context limit past the model's window, and saves off as null", async () => {
    await renderEdit({
      allowed_actions: ['edit', 'view', 'edit_policy'],
      config: { context_window_limit: 32000 },
      ...withModel(128_000),
    });
    await openAdvanced();
    const input = limitInput('contextLimitTokens');
    expect(input.value).toBe('32000');
    const save = buttonByText('agents.form.buttons.save');
    // Past the window is a note, not an error: the limit just has no effect.
    await act(async () => setNativeValue(input, '200000'));
    expect(save.disabled).toBe(false);
    expect(input.getAttribute('aria-invalid')).toBeNull();
    expect(container.textContent).toContain(
      'agents.form.advanced.contextLimitAboveWindow',
    );
    // Below the server's floor is an error.
    await act(async () => setNativeValue(input, '12000'));
    expect(save.disabled).toBe(true);
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(container.textContent).toContain('agents.form.advanced.limitRange');
    // Emptied while on is not a value either.
    await act(async () => setNativeValue(input, ''));
    expect(save.disabled).toBe(true);
    await act(async () => limitSwitch('contextLimit').click());
    expect(save.disabled).toBe(false);
    await act(async () => save.click());
    expect(sentConfig().context_window_limit).toBeNull();
  });

  it("does not block saving a stored limit past the model's window", async () => {
    // Without edit_policy the limit can't be changed, so it must not hold
    // back an unrelated save.
    await renderEdit({
      config: { context_window_limit: 200_000, history_token_limit: 150_000 },
      ...withModel(128_000),
    });
    await openAdvanced();
    expect(container.textContent).toContain(
      'agents.form.advanced.contextLimitAboveWindow',
    );
    expect(container.textContent).toContain(
      'agents.form.advanced.historyLimitAboveWindow',
    );
    const name = container.querySelector<HTMLInputElement>(
      'input[placeholder="agents.form.placeholders.agentName"]',
    )!;
    await act(async () => setNativeValue(name, 'Renamed'));
    await act(async () => buttonByText('agents.form.buttons.save').click());
    expect(sentConfig()).toMatchObject({
      context_window_limit: 200_000,
      history_token_limit: 150_000,
    });
  });

  it('keeps the history limit below the context limit', async () => {
    await renderEdit({
      allowed_actions: ['edit', 'view', 'edit_policy'],
      config: { context_window_limit: 32000 },
      ...withModel(128_000),
    });
    await openAdvanced();
    await act(async () => limitSwitch('historyLimit').click());
    const input = limitInput('historyLimitTokens');
    expect(input.value).toBe('8000');
    const save = buttonByText('agents.form.buttons.save');
    await act(async () => setNativeValue(input, '32000'));
    expect(save.disabled).toBe(true);
    expect(container.textContent).toContain(
      'agents.form.advanced.historyLimitBelowContext',
    );
    await act(async () => setNativeValue(input, '16000'));
    await act(async () => save.click());
    expect(sentConfig()).toMatchObject({
      context_window_limit: 32000,
      history_token_limit: 16000,
    });
  });

  it('shows the limits read-only without edit_policy', async () => {
    await renderEdit({
      config: { context_window_limit: 32000, history_token_limit: 8000 },
    });
    await openAdvanced();
    expect(limitInput('contextLimitTokens').disabled).toBe(true);
    expect(limitInput('historyLimitTokens').disabled).toBe(true);
    expect(limitSwitch('contextLimit').disabled).toBe(true);
    expect(limitSwitch('historyLimit').disabled).toBe(true);
  });

  it('edits the starters and saves them cleaned', async () => {
    await renderEdit({ starters: ['Run due diligence on a new vendor'] });
    const fields = () =>
      Array.from(
        container.querySelectorAll<HTMLInputElement>('input[maxlength="200"]'),
      );
    // The saved starter, and a link for another (they are optional).
    expect(fields().map((f) => f.value)).toEqual([
      'Run due diligence on a new vendor',
    ]);
    await act(async () => buttonByText('agents.form.starters.add').click());
    await act(async () => buttonByText('agents.form.starters.add').click());
    const save = buttonByText('agents.form.buttons.save');
    await act(async () => setNativeValue(fields()[2], '  Which DPAs?  '));
    await act(async () => save.click());
    const sent = mocks.updateAgent.mock.calls[0][1];
    expect(JSON.parse(sent.get('starters') as string)).toEqual([
      'Run due diligence on a new vendor',
      'Which DPAs?',
    ]);
  });

  it('shows no starter fields until one is added', async () => {
    await renderEdit({ starters: [] });
    expect(container.querySelectorAll('input[maxlength="200"]')).toHaveLength(
      0,
    );
    expect(buttonByText('agents.form.starters.add')).toBeTruthy();
  });

  it('places Starters between Model and Advanced', async () => {
    await renderEdit({ starters: [] });
    const text = container.textContent ?? '';
    const at = (key: string) => text.indexOf(key);
    expect(at('agents.form.sections.model')).toBeLessThan(
      at('agents.form.sections.starters'),
    );
    expect(at('agents.form.sections.starters')).toBeLessThan(
      at('agents.form.sections.advanced'),
    );
  });

  it('removes a stopped item from the agent', async () => {
    await renderEdit(withStoppedTool({ reason: 'deleted', sponsor: null }));
    expect(container.textContent).toContain(
      'agents.form.resourceStates.reason.deleted',
    );
    await act(async () =>
      buttonByText('agents.form.resourceStates.remove').click(),
    );
    // Off the form, so off the notice too.
    expect(container.textContent).not.toContain(
      'agents.form.resourceStates.reason.deleted',
    );
    await act(async () => buttonByText('agents.form.buttons.save').click());
    const sent = mocks.updateAgent.mock.calls[0][1];
    expect(JSON.parse(sent.get('tools') as string)).toEqual([]);
  });

  it('reconnects the account of a stopped tool in place', async () => {
    mocks.reconnect.mockClear();
    await renderEdit(
      withStoppedTool({
        reason: 'connection_needs_reconnect',
        sponsor: null,
        can_confirm: false,
        can_reconnect: true,
        connection: { id: 'c1', connector_key: 'telegram', name: 'Telegram' },
      }),
    );
    await act(async () =>
      buttonByText('settings.connectors.status.reconnect').click(),
    );
    expect(mocks.reconnect).toHaveBeenCalledWith(
      { id: 'c1', connector_key: 'telegram' },
      undefined,
    );
  });

  it('explains an outdated confirmation and reloads the sponsors', async () => {
    mocks.updateAgent.mockImplementationOnce(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            success: false,
            code: 'sponsor_confirmation_unexpected',
            message: 'raw english',
            unexpected: ['tool:t1'],
          }),
          { status: 400 },
        ),
      ),
    );
    await renderEdit({});
    await rename('Renamed');
    await act(async () => buttonByText('agents.form.buttons.save').click());
    expect(container.textContent).toContain(
      'agents.form.sponsors.confirmationOutdated',
    );
    expect(container.textContent).not.toContain('raw english');
    expect(mocks.getAgent).toHaveBeenCalledTimes(2);
  });

  it('labels every picker with a floating label', async () => {
    await render();
    const labels = Array.from(
      container.querySelectorAll('[data-slot="form-field-label"]'),
    ).map((l) => l.textContent);
    expect(labels).toEqual(
      expect.arrayContaining([
        'agents.form.labels.name',
        'agents.form.labels.description',
        'agents.form.labels.sources',
        'agents.form.sections.tools',
        'agents.form.sections.agentType',
        'agents.form.sections.models',
      ]),
    );
  });

  it('gives each picker trigger the combobox role', async () => {
    await render();
    const triggers = Array.from(
      container.querySelectorAll('[data-testid="picker"] > button'),
    );
    expect(triggers).toHaveLength(3);
    triggers.forEach((trigger) =>
      expect(trigger.getAttribute('role')).toBe('combobox'),
    );
  });

  it('puts Sources beside Tools in a two-up field grid', async () => {
    await render();
    const [sources, tools] = Array.from(
      container.querySelectorAll('[data-testid="picker"] > button'),
    );
    const grid = sources.closest('.grid')!;
    expect(grid.className).toContain('sm:grid-cols-2');
    expect(grid.contains(tools)).toBe(true);
  });

  it('titles the new-agent page and puts its actions in the agent toolbar', async () => {
    await render();
    expect(container.querySelector('h1')?.textContent).toBe('agents.newAgent');
    const toolbar = container.querySelector('[data-slot="page-toolbar"]')!;
    expect(toolbar.textContent).toContain('agents.form.byline.new');
    expect(toolbar.contains(buttonByText('agents.form.buttons.publish'))).toBe(
      true,
    );
  });

  // Before publishing, Preview can only say "Publish to preview", so it is a
  // ⋯ item beside the title rather than a toolbar button.
  it('drops the New agent title once the agent is saved', async () => {
    await render();
    mocks.createAgent.mockImplementationOnce(() =>
      jsonResponse({ id: 'agent-1' }),
    );
    await act(async () =>
      buttonByText('agents.form.buttons.saveDraft').click(),
    );
    expect(container.querySelector('h1')?.textContent).not.toBe(
      'agents.newAgent',
    );
  });

  // The preview talks to the saved agent; Redux must hold that snapshot, not
  // the unsaved form, or the preview picks up an unsaved model.
  it('keeps the preview on the saved agent while editing a published one', async () => {
    mocks.getAgent.mockImplementationOnce(() =>
      jsonResponse({
        id: 'agent-1',
        name: 'Saved name',
        description: 'Saved description',
        status: 'published',
        agent_type: 'classic',
        prompt_id: 'default',
      }),
    );
    await act(async () => {
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
    const name = container.querySelector<HTMLInputElement>(
      'input[placeholder="agents.form.placeholders.agentName"]',
    )!;
    await act(async () => setNativeValue(name, 'Unsaved name'));

    const pushed = mocks.dispatch.mock.calls
      .map(([action]) => action)
      .filter((a) => a?.type === 'preference/setSelectedAgent' && a.payload);
    expect(pushed.length).toBeGreaterThan(0);
    for (const action of pushed) {
      expect(action.payload.name).toBe('Saved name');
    }
  });

  it('offers Preview from the toolbar menu until the agent is published', async () => {
    await render();
    const toolbar = container.querySelector('[data-slot="page-toolbar"]')!;
    expect(
      Array.from(toolbar.querySelectorAll('button')).some((b) =>
        b.textContent?.includes('agents.form.sections.preview'),
      ),
    ).toBe(false);
    const menu = container.querySelector<HTMLButtonElement>(
      'button[aria-label="agents.form.buttons.moreActions"]',
    )!;
    expect(menu.getAttribute('data-size')).toBe('icon');
    // Last in the toolbar row, after the page's buttons.
    expect(menu.closest('[data-slot="page-toolbar"]')).toBe(toolbar);
    expect(menu.parentElement!.lastElementChild).toBe(menu);
    await act(async () => {
      menu.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
    });
    const preview = Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((item) => item.textContent === 'agents.form.sections.preview')!;
    await act(async () => preview.click());
    const sheet = document.querySelector('[data-slot="sheet-content"]')!;
    expect(sheet.textContent).toContain('agents.form.preview.publishTitle');
  });

  // By the toolbar's width, as its row stacks: also with the drawer docked.
  it('stretches the main button while the toolbar row is stacked', async () => {
    await render();
    const publish = buttonByText('agents.form.buttons.publish')!;
    expect(publish.className).toContain('flex-1');
    expect(publish.className).toContain('@2xl:flex-none');
    expect(publish.className).not.toContain('sm:flex-none');
  });

  // The sidebar (and the agent card's menu) already switch between an
  // agent's pages, so the pages carry no pill row.
  it('has no destination pills', async () => {
    await render();
    expect(container.querySelector('[data-testid="section-pills"]')).toBeNull();
  });

  it('renders the Advanced header as a section-toggle', async () => {
    await render();
    const toggle = buttonByText('agents.form.sections.advanced');
    expect(toggle.getAttribute('data-variant')).toBe('section-toggle');
    expect(toggle.getAttribute('data-size')).toBe('sm');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    const chevron = toggle.firstElementChild!;
    expect(chevron.matches('svg.lucide-chevron-right')).toBe(true);
    expect(chevron.getAttribute('class')).not.toContain('rotate-90');
    expect(toggle.querySelectorAll('svg')).toHaveLength(1);
    expect(toggle.querySelector('h2')).toBeNull();
    expect(toggle.parentElement!.tagName).toBe('H2');
    const panel = toggle.closest('[data-slot="card"]')!;
    expect(panel.className).toContain(
      'has-[[data-variant=section-toggle]:focus-visible]:ring-3',
    );

    await act(async () => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(chevron.getAttribute('class')).toContain('rotate-90');
  });

  it('renders the description as a default-size ui Textarea at its own height', async () => {
    await render();
    const description = container.querySelector(
      'textarea[placeholder="agents.form.placeholders.describeAgent"]',
    )!;
    expect(description.getAttribute('data-slot')).toBe('textarea');
    expect(description.getAttribute('data-size')).toBe('default');
    expect(description.className).toContain('h-32');
    expect(description.className).toContain('sm:h-24');
  });

  it('renders the pickers as square comboboxes, muted while empty', async () => {
    await render();
    const triggers = Array.from(
      container.querySelectorAll('[data-testid="picker"] > button'),
    );
    // Sources, tools, models.
    expect(triggers).toHaveLength(3);
    for (const trigger of triggers) {
      expect(trigger.getAttribute('data-variant')).toBe('combobox');
      expect(trigger.getAttribute('data-size')).toBe('field');
      expect(trigger.getAttribute('data-shape')).toBe('default');
      expect(trigger.className).toContain('rounded-md');
      expect(trigger.hasAttribute('data-placeholder')).toBe(true);
      expect(trigger.querySelector('span.truncate')).not.toBeNull();
    }
  });

  it("gives the tool and knowledge pickers the chat pickers' chrome", async () => {
    await render();
    const [sources, tools] = Array.from(
      container.querySelectorAll<HTMLElement>('[data-testid="picker"]'),
    );
    expect(sources.dataset.title).toBe('conversation.sources.knowledge');
    expect(sources.dataset.search).toBe(
      'agents.form.sourcePopup.searchPlaceholder',
    );
    // The sources on the agent come first too.
    expect(sources.dataset.selectedFirst).toBe('true');
    expect(tools.dataset.title).toBe('settings.tools.label');
    expect(tools.dataset.search).toBe('settings.tools.searchPlaceholder');
    expect(tools.dataset.selectedFirst).toBe('true');
    // The Go to Tools footer every picker has.
    const footer = tools.querySelector('[data-testid="picker-footer"]')!;
    expect(footer.querySelector('a')?.getAttribute('href')).toBe(
      '/settings/tools',
    );
    expect(footer.textContent).toContain('settings.tools.manageTools');
    expect(footer.textContent).toContain('settings.tools.addTool');
  });

  it('filters the tools picker by kind past ten tools', async () => {
    mocks.tools = [
      ...Array.from({ length: 10 }, (_, i) => ({
        id: `api-${i}`,
        name: 'api_tool',
        display_name: `API ${i}`,
      })),
      { id: 'notes', name: 'notes', display_name: 'Notes' },
    ];
    await render();
    const tools = container.querySelectorAll('[data-testid="picker"]')[1];
    const kinds = Array.from(
      tools.querySelectorAll<HTMLButtonElement>(
        '[data-testid="picker-filters"] [data-slot="toggle-group-item"]',
      ),
    );
    expect(kinds.map((kind) => kind.firstChild?.textContent)).toEqual([
      'settings.tools.filters.all',
      'settings.tools.groupAdded',
      'agents.form.toolsPopup.groupCustom',
    ]);
    await act(async () => kinds[1].click());
    expect(
      Array.from(tools.querySelectorAll('[data-item]')).map((item) =>
        item.getAttribute('data-item'),
      ),
    ).toEqual(['notes']);
  });

  it('draws no tool kind track for a short list', async () => {
    mocks.tools = [
      { id: 'custom', name: 'api_tool', display_name: 'My API' },
      { id: 'notes', name: 'notes', display_name: 'Notes' },
    ];
    await render();
    const tools = container.querySelectorAll('[data-testid="picker"]')[1];
    expect(
      tools.querySelector('[data-testid="picker-filters"]')?.childElementCount,
    ).toBe(0);
  });

  it("says what each builder picker didn't find, with no lone heading", async () => {
    await render();
    const [sources, tools] = Array.from(
      container.querySelectorAll<HTMLElement>('[data-testid="picker"]'),
    );
    expect(sources.dataset.empty).toBe('settings.sources.noKnowledgeFound');
    // Knowledge is always grouped Yours / Shared with team.
    expect(sources.dataset.loneGroupHeading).toBe('false');
    expect(tools.dataset.empty).toBe('settings.tools.noToolsFound');
    expect(tools.dataset.loneGroupHeading).toBe('false');
  });

  it('adds a tool from the picker and puts it on the agent', async () => {
    mocks.tools = [{ id: 'mine', name: 'api_tool', display_name: 'My API' }];
    await render();
    const tools = container.querySelectorAll('[data-testid="picker"]')[1];
    const add = Array.from(
      tools.querySelectorAll<HTMLButtonElement>(
        '[data-testid="picker-footer"] button',
      ),
    ).find((b) => b.textContent === 'settings.tools.addTool')!;
    await act(async () => add.click());
    expect(mocks.addToolProps?.modalState).toBe('ACTIVE');
    const calls = mocks.toolsCalls.length;
    mocks.tools = [
      { id: 'mine', name: 'api_tool', display_name: 'My API' },
      { id: 'fresh', name: 'notes', display_name: 'Fresh notes' },
    ];
    await act(async () => mocks.addToolProps!.onToolsCreated(['fresh']));
    expect(mocks.toolsCalls.length).toBeGreaterThan(calls);
    const trigger = container.querySelectorAll(
      '[data-testid="picker"] > button',
    )[1];
    expect(trigger.textContent).toBe('Fresh notes');
  });

  it('shows the device status as a Badge once the picker opens', async () => {
    await render();
    expect(container.querySelector('[data-slot="badge"]')).toBeNull();
    const tools = Array.from(
      container.querySelectorAll('[data-testid="picker"]'),
    ).find(
      (picker) => picker.getAttribute('data-title') === 'settings.tools.label',
    )!;
    await act(async () =>
      tools
        .querySelector<HTMLButtonElement>('[data-testid="picker-open"]')!
        .click(),
    );
    const badge = container.querySelector('[data-slot="badge"]');
    expect(badge?.textContent).toBe('settings.devices.online');
    expect(badge?.getAttribute('data-variant')).toBe('success');
  });

  it('renders Save draft and Publish as pill button variants', async () => {
    await render();
    // A4: one purple button per page; every header button is field pill.
    const draft = buttonByText('agents.form.buttons.saveDraft');
    expect(draft.getAttribute('data-variant')).toBe('outline');
    expect(draft.getAttribute('data-size')).toBe('field');
    expect(draft.getAttribute('data-shape')).toBe('pill');
    const publish = buttonByText('agents.form.buttons.publish');
    expect(publish.getAttribute('data-variant')).toBe('default');
    expect(publish.getAttribute('data-size')).toBe('field');
    expect(publish.getAttribute('data-shape')).toBe('pill');
    expect(publish.disabled).toBe(true);
  });

  // Item 42: the header's Cancel (shown once the form is dirty) is ghost.
  it('renders the header Cancel as a ghost pill once the form changes', async () => {
    await render();
    const name = container.querySelector<HTMLInputElement>(
      'input[placeholder="agents.form.placeholders.agentName"]',
    )!;
    await act(async () => setNativeValue(name, 'Support bot'));
    const cancel = buttonByText('agents.form.buttons.cancel');
    expect(cancel.getAttribute('data-variant')).toBe('ghost');
    expect(cancel.getAttribute('data-size')).toBe('field');
    expect(cancel.getAttribute('data-shape')).toBe('pill');
  });

  it('shows a failed save as a destructive alert with an icon', async () => {
    await render();
    const draft = buttonByText('agents.form.buttons.saveDraft');
    await act(async () => draft.click());
    const alert = container.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('Name is taken');
    // ui/alert's destructive variant.
    expect(alert.className).toContain('border-destructive/50');
    expect(alert.className).toContain('bg-destructive/10');
    expect(alert.querySelector('svg.lucide-circle-alert')).not.toBeNull();
    // Decision 69 (b): the notice sits above the form panel, not in the
    // header's button row.
    expect(draft.parentElement?.contains(alert)).toBe(false);
  });

  it('marks JSON schema validity with token colours and lucide icons', async () => {
    await render();
    await act(async () =>
      buttonByText('agents.form.sections.advanced').click(),
    );
    const schema = Array.from(container.querySelectorAll('textarea')).find(
      (el) => el.className.includes('font-mono'),
    )!;
    expect(schema.getAttribute('data-slot')).toBe('textarea');
    expect(schema.getAttribute('data-size')).toBe('default');

    await act(async () => setNativeValue(schema, '{ not json'));
    const invalid = Array.from(container.querySelectorAll('div')).find(
      (el) => el.textContent === 'agents.form.advanced.invalidJson',
    )!;
    expect(invalid.className).toContain('text-destructive');
    expect(invalid.querySelector('svg.lucide-circle-x')).not.toBeNull();

    await act(async () => setNativeValue(schema, '{}'));
    const valid = Array.from(container.querySelectorAll('div')).find(
      (el) => el.textContent === 'agents.form.advanced.validJson',
    )!;
    expect(valid.className).toContain('text-success');
    expect(valid.querySelector('svg.lucide-circle-check')).not.toBeNull();
  });

  // Card surfaces: the form is a place, so each section is a subtle panel
  // straight on the page, with no muted panel around the form.
  it('draws each form section as a subtle panel on the page', async () => {
    await render();
    const titles = Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="section-header"]'),
    );
    expect(titles.length).toBeGreaterThan(0);
    for (const title of titles) {
      const panel = title.closest<HTMLElement>('[data-slot="card"]')!;
      expect(panel.dataset.variant).toBe(
        title.closest('[data-tone="destructive"]')
          ? panel.dataset.variant
          : 'subtle',
      );
    }
    const advanced = buttonByText('agents.form.sections.advanced');
    const panel = advanced.closest<HTMLElement>('[data-slot="card"]')!;
    expect(panel.dataset.variant).toBe('subtle');
    expect(panel.dataset.padding).toBe('lg');
    expect(container.querySelector('.bg-muted.rounded-2xl')).toBeNull();
  });

  it('notches floating labels on the page background', async () => {
    await render();
    const labels = Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="form-field-label"]'),
    );
    expect(labels.length).toBeGreaterThan(0);
    for (const label of labels) {
      expect(label.className).toContain('bg-background');
    }
  });
});

describe('NewAgent gating by role', () => {
  let container: HTMLDivElement;
  let root: Root;

  const OWNER = [
    'delete',
    'edit',
    'edit_policy',
    'export',
    'manage_access_details',
    'manage_schedules',
    'manage_settings',
    'move_folder',
    'pin',
    'publish',
    'share',
    'use',
    'view',
    'view_logs',
  ];
  const EDITOR = [
    'edit',
    'edit_policy',
    'export',
    'manage_access_details',
    'manage_schedules',
    'pin',
    'publish',
    'use',
    'view',
    'view_logs',
  ];

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    mocks.dispatch.mockClear();
    mocks.getAgent.mockReset();
    mocks.getAgent.mockImplementation(() => jsonResponse({}));
    mocks.deleteAgent.mockReset();
    mocks.deleteAgent.mockImplementation(() => jsonResponse({}));
    mocks.guardrailsProps.mockClear();
  });

  const renderEdit = async (access: 'owner' | 'editor', allowed: string[]) => {
    mocks.getAgent.mockImplementation(() =>
      jsonResponse({
        id: 'agent-1',
        name: 'Deal Desk',
        description: 'Researches deals',
        status: 'published',
        agent_type: 'classic',
        prompt_id: 'default',
        ownership: access === 'owner' ? 'user' : 'team',
        team_access: access === 'owner' ? null : access,
        access,
        allowed_actions: allowed,
      }),
    );
    await act(async () => {
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
  };

  const buttonByText = (text: string) =>
    Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes(text),
    );

  const menuLabels = async () => {
    const menu = container.querySelector<HTMLButtonElement>(
      'button[aria-label="agents.form.buttons.moreActions"]',
    )!;
    await act(async () => {
      menu.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
    });
    return Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).map((item) => item.textContent);
  };

  const lastGuardrailsDisabled = () =>
    mocks.guardrailsProps.mock.calls.at(-1)?.[0].disabled;

  it('gives the owner Access details, Share and Delete', async () => {
    await renderEdit('owner', OWNER);
    expect(await menuLabels()).toEqual([
      'agents.form.buttons.accessDetails',
      'agents.shareWithTeam',
      'agents.form.buttons.delete',
    ]);
  });

  // Delete is the menu's last item, set apart by a rule, as on a source's
  // and a workflow's ⋯; the form has no danger zone.
  it('puts Delete last in the menu, after a rule', async () => {
    await renderEdit('owner', OWNER);
    await menuLabels();
    const items = Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    );
    const del = items.at(-1)!;
    expect(del.textContent).toBe('agents.form.buttons.delete');
    expect(del.dataset.variant).toBe('destructive');
    expect(del.previousElementSibling?.getAttribute('role')).toBe('separator');
  });

  it('hides Share and Delete from an editor but keeps Access details', async () => {
    await renderEdit('editor', EDITOR);
    expect(await menuLabels()).toEqual(['agents.form.buttons.accessDetails']);
  });

  it('lets an editor change guardrails and quotas', async () => {
    await renderEdit('editor', EDITOR);
    expect(lastGuardrailsDisabled()).toBe(false);
    await act(async () =>
      buttonByText('agents.form.sections.advanced')!.click(),
    );
    const switches =
      container.querySelectorAll<HTMLButtonElement>('[role="switch"]');
    expect(switches.length).toBeGreaterThan(0);
    for (const s of Array.from(switches)) expect(s.disabled).toBe(false);
  });

  it('locks guardrails and quotas without edit_policy', async () => {
    await renderEdit(
      'editor',
      EDITOR.filter((a) => a !== 'edit_policy'),
    );
    expect(lastGuardrailsDisabled()).toBe(true);
    await act(async () =>
      buttonByText('agents.form.sections.advanced')!.click(),
    );
    const token = container.querySelector<HTMLInputElement>(
      'input[placeholder="agents.form.placeholders.enterTokenLimit"]',
    )!;
    const tokenSwitch = token
      .closest('[data-slot="setting-row"]')
      ?.querySelector<HTMLButtonElement>('[role="switch"]');
    expect(tokenSwitch?.disabled).toBe(true);
    expect(token.disabled).toBe(true);
  });

  it('keeps the form clean after the API write allowlist saves', async () => {
    await renderEdit('owner', OWNER);
    const details = () =>
      mocks.detailsProps.mock.calls.at(-1)![0] as {
        onConfigChange: (config: Record<string, unknown>) => void;
        getSavedConfig: () => Record<string, unknown> | undefined;
      };
    const saved = {
      ...details().getSavedConfig(),
      api_write_allowlist: ['tool-1:send'],
    };
    await act(async () => details().onConfigChange(saved));
    expect(details().getSavedConfig()).toEqual(saved);
    expect(buttonByText('agents.form.buttons.cancel')).toBeUndefined();
  });

  // "What this agent uses" in Share sends the owner to the API write
  // allowlist, which opens unfolded; opened any other way it starts folded.
  it('opens Access details on the allowlist from Share', async () => {
    await renderEdit('owner', OWNER);
    const details = () =>
      mocks.detailsProps.mock.calls.at(-1)![0] as {
        modalState: string;
        openApiWrites?: boolean;
        setModalState: (state: string) => void;
      };
    await menuLabels();
    await act(async () =>
      Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]'))
        .find((item) => item.textContent === 'agents.shareWithTeam')!
        .click(),
    );
    const share = mocks.shareProps.mock.calls.at(-1)![0] as {
      onOpenAccessDetails?: () => void;
    };
    mocks.shareProps.mockClear();
    await act(async () => share.onOpenAccessDetails!());
    expect(mocks.shareProps).not.toHaveBeenCalled();
    expect(details().modalState).toBe('ACTIVE');
    expect(details().openApiWrites).toBe(true);
    await act(async () => details().setModalState('INACTIVE'));
    expect(details().openApiWrites).toBe(false);
  });

  it('gives Share no way to Access details without manage_access_details', async () => {
    await renderEdit(
      'owner',
      OWNER.filter((a) => a !== 'manage_access_details'),
    );
    await menuLabels();
    await act(async () =>
      Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]'))
        .find((item) => item.textContent === 'agents.shareWithTeam')!
        .click(),
    );
    const share = mocks.shareProps.mock.calls.at(-1)![0] as {
      onOpenAccessDetails?: () => void;
    };
    expect(share.onOpenAccessDetails).toBeUndefined();
  });

  it('hides Access details without manage_access_details', async () => {
    await renderEdit(
      'editor',
      EDITOR.filter((a) => a !== 'manage_access_details'),
    );
    // With nothing to offer, the ⋯ isn't drawn.
    expect(
      container.querySelector(
        'button[aria-label="agents.form.buttons.moreActions"]',
      ),
    ).toBeNull();
  });

  it('keeps a failed delete in the dialog with the server message', async () => {
    mocks.deleteAgent.mockImplementation(() =>
      jsonResponse({ message: 'Only the owner can delete' }, false),
    );
    await renderEdit('owner', OWNER);
    await menuLabels();
    await act(async () =>
      Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]'))
        .find((item) => item.textContent === 'agents.form.buttons.delete')!
        .click(),
    );
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-testid="confirm-delete"]')!
        .click(),
    );
    await expect(mocks.submitResult).rejects.toThrow();
    await act(async () => undefined);
    expect(
      container.querySelector('[data-testid="confirm-error"]')!.textContent,
    ).toBe('Only the owner can delete');
    expect(mocks.dispatch).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: 'actionToast/showActionToast' }),
    );
  });
});

describe('NewAgent drafter', () => {
  let container: HTMLDivElement;
  let root: Root;

  const PROMPT_TEXT = 'You help customers with shipping.';
  const proposal = (
    fields: Record<string, unknown>,
    progress: { steps?: string[]; next_step?: string | null } = {},
  ) => ({
    type: 'proposal',
    proposal: {
      message: 'The draft is in the form.',
      fields,
      reasons: [{ field: 'name', summary: 'Shipping help' }],
      notes: [],
      dropped: [],
      steps: progress.steps ?? [],
      next_step: progress.next_step ?? null,
    },
  });

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    drafter.config = {
      enabled: true,
      model: { id: 'm1', display_name: 'Fast model' },
      reason: null,
    };
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    drafter.config = null;
    drafter.scripts = [];
    drafter.requests = [];
    mocks.createAgent.mockReset();
    mocks.createAgent.mockImplementation(() =>
      jsonResponse({ message: 'Name is taken' }, false),
    );
    mocks.createPrompt.mockReset();
    mocks.createPrompt.mockImplementation(() => jsonResponse({}));
    mocks.getAgent.mockReset();
    mocks.getAgent.mockImplementation(() => jsonResponse({}));
    mocks.guardrailsProps.mockClear();
    mocks.tools = null;
    media.isMobile = false;
    media.isDesktop = true;
  });

  const render = async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <NewAgent mode="new" />
          <RouterProbe />
        </MemoryRouter>,
      );
    });
  };

  const renderEdit = async (
    allowed: string[],
    over: Record<string, unknown> = {},
  ) => {
    mocks.getAgent.mockImplementation(() =>
      jsonResponse({
        id: 'agent-1',
        name: 'Deal Desk',
        description: 'Researches deals',
        status: 'published',
        agent_type: 'classic',
        prompt_id: 'default',
        access: 'viewer',
        allowed_actions: allowed,
        ...over,
      }),
    );
    await act(async () => {
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
  };

  const buttons = (root: ParentNode = container) =>
    Array.from(root.querySelectorAll<HTMLButtonElement>('button'));
  const buttonByText = (text: string, root: ParentNode = container) =>
    buttons(root).find((b) => b.textContent?.includes(text));
  const buttonByLabel = (label: string, root: ParentNode = container) =>
    buttons(root).find((b) => b.getAttribute('aria-label') === label);
  const wand = () =>
    buttons().find(
      (b) => b.hasAttribute('data-drafter-entry') && b.textContent !== '',
    );
  // A closed docked panel stays mounted, inert, while it shrinks out.
  const panel = () =>
    document.querySelector<HTMLElement>(
      '[data-slot="side-panel"][data-state="open"], [data-slot="sheet-content"]',
    );
  const nameInput = () =>
    container.querySelector<HTMLInputElement>(
      'input[placeholder="agents.form.placeholders.agentName"]',
    )!;
  const drafted = () =>
    Array.from(container.querySelectorAll('[data-drafted]')).map(
      (el) => el.querySelector('label')?.textContent,
    );
  const lastRequest = () => drafter.requests.at(-1)!;

  /** Open the drawer (unless it is open) and send a message from its composer. */
  const ask = async (text: string) => {
    if (!panel()) await act(async () => wand()!.click());
    const input = panel()!.querySelector<HTMLTextAreaElement>(
      'textarea[aria-label="drafter.askLabel"]',
    )!;
    await act(async () => setNativeValue(input, text));
    await act(async () => buttonByLabel('drafter.send', panel()!)!.click());
  };
  /** The latest turn's Next (or Finish). */
  const next = () =>
    buttons(panel()!).find(
      (b) =>
        b.textContent === 'drafter.agent.build.next' ||
        b.textContent === 'drafter.agent.build.finish',
    );

  it('shows no wand while the drafter is off', async () => {
    drafter.config = { enabled: false, model: null, reason: null };
    await render();
    expect(wand()).toBeUndefined();
    expect(panel()).toBeNull();
  });

  it("hides the wand from someone who can't edit the agent", async () => {
    await renderEdit(['use', 'view']);
    expect(wand()).toBeUndefined();
  });

  it('shows no wand until the agent says what the caller may do', async () => {
    let answer: (value: {
      ok: boolean;
      json: () => Promise<unknown>;
    }) => void = () => undefined;
    mocks.getAgent.mockImplementation(
      () =>
        new Promise((resolve) => {
          answer = resolve;
        }),
    );
    await act(async () => {
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
    // Still loading: the form's stub has no access fields to read.
    expect(wand()).toBeUndefined();
    await act(async () =>
      answer({
        ok: true,
        json: () =>
          Promise.resolve({
            id: 'agent-1',
            name: 'Deal Desk',
            status: 'published',
            access: 'editor',
            allowed_actions: ['edit', 'publish', 'use', 'view'],
          }),
      }),
    );
    expect(wand()).toBeDefined();
  });

  it('reads Improve on a saved agent with an empty form, as its drawer runs', async () => {
    await renderEdit(['edit', 'publish', 'use', 'view'], {
      name: '',
      description: '',
    });
    expect(wand()!.textContent).toContain('drafter.improve');
    await act(async () => wand()!.click());
    expect(panel()!.textContent).not.toContain('drafter.agent.build.intro');
  });

  it('loads an agent without its switch settings as off, with no warning', async () => {
    const error = vi
      .spyOn(console, 'error')
      .mockImplementation(() => undefined);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    await renderEdit(['edit', 'publish', 'use', 'view']);
    // The Advanced panel draws the switch once open.
    await act(async () =>
      buttonByText('agents.form.sections.advanced')!.click(),
    );
    expect(
      [...error.mock.calls, ...warn.mock.calls].filter((call) =>
        /uncontrolled/i.test(String(call[0])),
      ),
    ).toEqual([]);
    error.mockRestore();
    warn.mockRestore();
  });

  it('offers Improve on a filled agent, left of Preview', async () => {
    await renderEdit(['edit', 'publish', 'use', 'view']);
    expect(wand()!.textContent).toContain('drafter.improve');
    const row = buttons().filter(
      (b) =>
        b === wand() || b.textContent?.includes('agents.form.sections.preview'),
    );
    expect(row[0]).toBe(wand());
  });

  it('greets an empty new agent with the plan and starts at Basics', async () => {
    await render();
    expect(wand()!.textContent).toContain('drafter.draft');
    // No describe box on the form.
    expect(container.querySelector('textarea[rows="3"]')).toBeNull();
    await act(async () => wand()!.click());
    expect(panel()!.textContent).toContain('drafter.agent.build.intro');
    expect(
      panel()!
        .querySelector('textarea[aria-label="drafter.askLabel"]')
        ?.getAttribute('placeholder'),
    ).toBe('drafter.agent.build.describePlaceholder');
    // A starting point sends its title and begins the build from its id.
    expect(panel()!.textContent).toContain(
      'drafter.starters.website.titledrafter.starters.website.description',
    );
    await act(async () =>
      buttonByText('drafter.starters.website.title', panel()!)!.click(),
    );
    expect(drafter.requests).toHaveLength(1);
    expect(drafter.requests[0]).toMatchObject({
      recipe: 'agent',
      messages: [{ role: 'user', content: 'drafter.starters.website.title' }],
      context: {
        agent_id: null,
        step: 'basics',
        earlier: [],
        starter: 'website',
        form: {
          name: '',
          description: '',
          agent_type: 'classic',
          sources: [],
          tools: [],
          prompt_id: 'default',
          prompt_draft: null,
          starters: [],
          limits: { mode: 'none', value: null },
          analytics: { enabled: true, topics: [], hidden_folders: [] },
        },
      },
    });
    expect(drafter.requests[0].context.form).not.toHaveProperty(
      'pending_prompt',
    );
    expect(panel()!.textContent).toContain('drafter.agent.build.progress');
  });

  it('fills the form from a proposal, marks each field, and undoes one', async () => {
    mocks.tools = [
      { id: 'tool-1', name: 'api_tool', display_name: 'Tracking' },
    ];
    drafter.scripts = [
      [
        proposal({
          name: 'Shipping help',
          description: 'Answers shipping questions.',
          agent_type: 'research',
          tools: ['tool-1'],
          starters: ['Where is my parcel?'],
        }),
        { type: 'end' },
      ],
    ];
    await render();
    await ask('Shipping agent');
    expect(nameInput().value).toBe('Shipping help');
    expect(drafted()).toEqual([
      'agents.form.labels.name',
      'agents.form.labels.description',
      'agents.form.sections.tools',
      'agents.form.sections.agentType',
      'agents.form.starters.label',
    ]);
    expect(
      container.querySelector('[data-drafted] [data-slot="drafted-badge"]'),
    ).not.toBeNull();
    expect(panel()!.textContent).toContain('The draft is in the form.');
    // No drafted strip and no Undo all over the form.
    expect(container.querySelector('[data-slot="drafted-strip"]')).toBeNull();
    expect(buttonByText('drafter.undoAll')).toBeUndefined();

    await act(async () => buttonByLabel('drafter.undoField')!.click());
    expect(nameInput().value).toBe('');
    expect(drafted()).not.toContain('agents.form.labels.name');
  });

  it('gives reasons only for the fields the draft changed, and announces them', async () => {
    drafter.scripts = [
      [
        {
          type: 'proposal',
          proposal: {
            message: 'The draft is in the form.',
            // The form is already Classic: that field doesn't change.
            fields: { name: 'Shipping help', agent_type: 'classic' },
            reasons: [
              { field: 'name', summary: 'Says what it does' },
              { field: 'agent_type', summary: 'Classic suits Q&A' },
            ],
            notes: [],
            dropped: [],
          },
        },
        { type: 'end' },
      ],
    ];
    await render();
    await ask('Shipping agent');
    const summary = panel()!.querySelector('[data-slot="proposal-summary"]')!;
    expect(summary.textContent).toContain('Says what it does');
    expect(summary.textContent).not.toContain('Classic suits Q&A');
    expect(
      panel()!.querySelector('[data-slot="drafter-live"] .sr-only')
        ?.textContent,
    ).toBe('drafter.agent.draftedCount');
  });

  it('moves to the next step on Next, with the earlier words and a hidden message', async () => {
    drafter.scripts = [
      [
        proposal(
          { name: 'Shipping help desk', description: 'Answers shipping.' },
          { steps: ['basics'], next_step: 'knowledge' },
        ),
        { type: 'end' },
      ],
    ];
    await render();
    await ask('A shipping agent for our website');
    expect(
      panel()!
        .querySelector('textarea[aria-label="drafter.askLabel"]')
        ?.getAttribute('placeholder'),
    ).toBe('drafter.agent.build.changePlaceholder');
    await act(async () => next()!.click());
    expect(drafter.requests).toHaveLength(2);
    expect(lastRequest().messages).toEqual([
      { role: 'user', content: 'drafter.agent.build.continue' },
    ]);
    expect(lastRequest().context).toMatchObject({
      step: 'knowledge',
      earlier: ['A shipping agent for our website'],
      form: { name: 'Shipping help desk' },
    });
    // The step folds to a line; the hidden message draws no bubble.
    expect(
      panel()!.querySelector('[data-slot="build-finished"]')?.textContent,
    ).toContain('drafter.agent.build.folded');
    expect(panel()!.querySelector('[data-item="user"]')).toBeNull();
    // The step's marks stay on the form.
    expect(drafted()).toContain('agents.form.labels.name');
  });

  it('takes an empty proposal as the step approved and moves on', async () => {
    drafter.scripts = [
      [
        proposal({ name: 'Shipping help desk' }, { steps: ['basics'] }),
        { type: 'end' },
      ],
      [
        proposal({}, { steps: ['basics'], next_step: 'knowledge' }),
        { type: 'end' },
      ],
    ];
    await render();
    await ask('A shipping agent');
    await ask('ok, next');
    expect(drafter.requests).toHaveLength(3);
    expect(lastRequest().context.step).toBe('knowledge');
    expect(lastRequest().context.earlier).toEqual([
      'A shipping agent',
      'ok, next',
    ]);
  });

  it("doesn't move on when every part of a proposal was dropped", async () => {
    drafter.scripts = [
      [
        proposal({ name: 'Shipping help desk' }, { steps: ['basics'] }),
        { type: 'end' },
      ],
      [
        {
          type: 'proposal',
          proposal: {
            message: 'Added your handbook.',
            fields: {},
            reasons: [],
            notes: [],
            dropped: [{ field: 'sources', id: 'made-up', reason: 'not_found' }],
            steps: ['basics'],
            next_step: 'knowledge',
          },
        },
        { type: 'end' },
      ],
    ];
    await render();
    await ask('A shipping agent');
    await ask('Use the handbook');
    expect(drafter.requests).toHaveLength(2);
    expect(panel()!.textContent).toContain('drafter.agent.droppedLine');
    expect(next()).toBeDefined();
  });

  it('jumps past the steps one description covered', async () => {
    drafter.scripts = [
      [
        proposal(
          {
            name: 'Ops customs desk',
            prompt: { kind: 'existing', id: 'creative' },
          },
          { steps: ['basics', 'knowledge', 'prompt'], next_step: 'safety' },
        ),
        { type: 'end' },
      ],
    ];
    await render();
    await ask('Internal agent for the ops team, use the creative prompt');
    expect(
      buttonByText('drafter.agent.build.checkForm', panel()!),
    ).toBeTruthy();
    await act(async () => next()!.click());
    expect(lastRequest().context.step).toBe('safety');
    const header = panel()!.textContent!;
    expect(header).toContain('drafter.agent.build.filledAtOnce');
    // Three finished steps fold into one line.
    expect(
      panel()!.querySelectorAll(
        '[data-slot="build-finished"] > [data-slot="drafter-step-row"]',
      ),
    ).toHaveLength(1);
  });

  it('applies limits and guardrails from the safety step, and undoes them', async () => {
    drafter.scripts = [
      [
        proposal(
          { name: 'Shipping help desk' },
          { steps: ['basics', 'knowledge', 'prompt'], next_step: 'safety' },
        ),
        { type: 'end' },
      ],
      [
        proposal(
          {
            limits: { mode: 'requests', value: 500 },
            guardrails: { checks: ['pii', 'injection'] },
          },
          { steps: ['safety'] },
        ),
        { type: 'end' },
      ],
    ];
    await render();
    await ask('A public shipping agent');
    await act(async () => next()!.click());
    const requestLimit = () =>
      container.querySelector<HTMLInputElement>(
        'input[aria-label="agents.form.advanced.requestLimit"]',
      )!;
    // Advanced opens itself for the drafted limit.
    const advanced = buttonByText('agents.form.sections.advanced')!;
    expect(advanced.getAttribute('aria-expanded')).toBe('true');
    expect(requestLimit().value).toBe('500');
    expect(requestLimit().disabled).toBe(false);
    const requestRow = requestLimit().closest('[data-slot="setting-row"]')!;
    expect(requestRow.getAttribute('data-drafted')).toBe('true');
    const guardrails = mocks.guardrailsProps.mock.calls.at(-1)![0] as {
      drafted: boolean;
      value: { enabled: boolean; mode: string; controls: { check: string }[] };
    };
    expect(guardrails.drafted).toBe(true);
    expect(guardrails.value.enabled).toBe(true);
    expect(guardrails.value.mode).toBe('monitor_only');
    expect(guardrails.value.controls.map((c) => c.check)).toEqual([
      'pii',
      'pii',
      'injection',
    ]);
    expect(next()!.textContent).toBe('drafter.agent.build.finish');

    // The row's badge undoes the limit: both limits off again.
    await act(async () =>
      buttonByLabel('drafter.undoField', requestRow)!.click(),
    );
    expect(requestLimit().disabled).toBe(true);
    expect(
      requestLimit()
        .closest('[data-slot="setting-row"]')!
        .hasAttribute('data-drafted'),
    ).toBe(false);
    await act(async () =>
      (
        mocks.guardrailsProps.mock.calls.at(-1)![0] as { onUndo: () => void }
      ).onUndo(),
    );
    expect(
      (mocks.guardrailsProps.mock.calls.at(-1)![0] as { drafted: boolean })
        .drafted,
    ).toBe(false);

    await act(async () => next()!.click());
    expect(panel()!.textContent).toContain('drafter.agent.build.done');
    expect(panel()!.textContent).toContain('drafter.agent.build.allFilled');
  });

  it('starts the build over from the drawer, back at its plan', async () => {
    drafter.scripts = [
      [
        proposal({ name: 'Shipping help' }, { steps: ['basics'] }),
        { type: 'end' },
      ],
    ];
    await render();
    await ask('A shipping agent');
    expect(panel()!.textContent).toContain('drafter.agent.build.progress');
    await act(async () =>
      buttonByLabel('drafter.startOver', panel()!)!.click(),
    );
    // No step, no progress: the next message is free-form again.
    expect(panel()!.textContent).not.toContain('drafter.agent.build.progress');
    expect(panel()!.querySelector('[data-item="proposal"]')).toBeNull();
    await ask('Shorter name');
    expect(lastRequest().context.step).toBeNull();
  });

  it('reads Resume while a build is unfinished', async () => {
    drafter.scripts = [
      [
        proposal({ name: 'Shipping help desk' }, { steps: ['basics'] }),
        { type: 'end' },
      ],
    ];
    await render();
    await ask('A shipping agent');
    await act(async () => wand()!.click());
    expect(panel()).toBeNull();
    expect(wand()!.textContent).toContain('drafter.agent.build.resume');
    expect(wand()!.getAttribute('aria-label')).toBe(
      'drafter.agent.build.resumeLabel',
    );
    expect(wand()!.getAttribute('aria-expanded')).toBe('false');
  });

  it('offers improve rows on a saved agent, and Finish setup asks for safety', async () => {
    await renderEdit(['edit', 'edit_policy', 'publish', 'use', 'view']);
    await act(async () => wand()!.click());
    const text = panel()!.textContent!;
    expect(text).toContain('drafter.agent.improve.introPublished');
    expect(text).not.toContain('drafter.agent.build.progress');
    expect(
      buttons(panel()!)
        .map((b) => b.textContent)
        .filter((label) => label?.startsWith('drafter.agent.improve.')),
    ).toEqual([
      // What this agent lacks: no knowledge, the default prompt, no starters.
      'drafter.agent.improve.finishSetup',
      'drafter.agent.improve.knowledge',
      'drafter.agent.improve.writePrompt',
      'drafter.agent.improve.starters',
    ]);
    await act(async () =>
      buttonByText('drafter.agent.improve.finishSetup', panel()!)!.click(),
    );
    expect(lastRequest().context).toMatchObject({
      agent_id: 'agent-1',
      step: 'safety',
    });
    await ask('Make it friendlier');
    // The rest of the conversation stays on limits and safety.
    expect(lastRequest().context.step).toBe('safety');
  });

  it('leaves out Finish setup once limits or guardrails are set', async () => {
    await renderEdit(['edit', 'edit_policy', 'publish', 'use', 'view'], {
      status: 'draft',
      limited_request_mode: true,
      request_limit: 100,
    });
    await act(async () => wand()!.click());
    expect(panel()!.textContent).toContain('drafter.agent.improve.intro');
    expect(
      buttonByText('drafter.agent.improve.finishSetup', panel()!),
    ).toBeUndefined();
    await ask('Shorter');
    expect(lastRequest().context.step).toBeNull();
  });

  it('undoes a field drafted twice back to before the first draft', async () => {
    drafter.scripts = [
      [proposal({ limits: { mode: 'requests', value: 500 } }), { type: 'end' }],
      [proposal({ limits: { mode: 'requests', value: 300 } }), { type: 'end' }],
    ];
    await renderEdit(['edit', 'edit_policy', 'publish', 'use', 'view']);
    await ask('Cap it at 500');
    await ask('300 is enough');
    const requestLimit = () =>
      container.querySelector<HTMLInputElement>(
        'input[aria-label="agents.form.advanced.requestLimit"]',
      )!;
    expect(requestLimit().value).toBe('300');
    await act(async () =>
      buttonByLabel(
        'drafter.undoField',
        requestLimit().closest('[data-slot="setting-row"]')!,
      )!.click(),
    );
    // No limit, as the agent had before either draft.
    expect(requestLimit().disabled).toBe(true);
  });

  it('keeps the marks and the conversation of a draft that lands during Publish', async () => {
    let answer: (value: {
      ok: boolean;
      json: () => Promise<unknown>;
    }) => void = () => undefined;
    mocks.createAgent.mockImplementation(
      () =>
        new Promise((resolve) => {
          answer = resolve;
        }),
    );
    drafter.scripts = [
      [
        proposal(
          { name: 'Shipping help', description: 'Answers shipping.' },
          { steps: ['basics'] },
        ),
        { type: 'end' },
      ],
      [proposal({ starters: ['Where is my parcel?'] }), { type: 'end' }],
    ];
    await render();
    await ask('Shipping agent');
    await act(async () => buttonByText('agents.form.buttons.publish')!.click());
    await ask('Add a starter');
    await act(async () =>
      answer({ ok: true, json: () => Promise.resolve({ id: 'new-1' }) }),
    );
    // What was published loses its marks; the starter that came after keeps
    // its, and the drawer its conversation.
    expect(drafted()).toEqual(['agents.form.starters.label']);
    expect(
      panel()!.querySelectorAll('[data-slot="proposal-summary"]'),
    ).toHaveLength(2);
  });

  it('drops the mark of a field edited by hand', async () => {
    drafter.scripts = [[proposal({ name: 'Shipping help' }), { type: 'end' }]];
    await render();
    await ask('Shipping agent');
    expect(drafted()).toEqual(['agents.form.labels.name']);
    await act(async () => setNativeValue(nameInput(), 'My own name'));
    expect(drafted()).toEqual([]);
  });

  // Decision 64: a prompt it writes opens in the prompt view beside the
  // drawer; Use this prompt saves it and sets it on the agent.
  describe('the prompt step', () => {
    const WRITTEN = {
      kind: 'new',
      name: 'Shipping support',
      content: PROMPT_TEXT,
    };
    const writes = (content = PROMPT_TEXT) => [
      proposal(
        {
          prompt: { ...WRITTEN, content },
          starters: ['Where is my parcel?'],
        },
        { steps: ['basics', 'knowledge', 'prompt'], next_step: 'safety' },
      ),
      { type: 'end' },
    ];
    beforeEach(() => {
      mockState.preference.prompts = [
        { id: 'default', name: 'default', type: 'public' },
      ] as never[];
    });
    afterEach(() => {
      mockState.preference.prompts = [];
      mocks.updatePrompt.mockClear();
    });

    const view = () =>
      container.querySelector<HTMLElement>('[data-slot="prompt-view"]');
    const viewName = () =>
      view()!.querySelector<HTMLInputElement>('input[type="text"]')!;
    const viewText = () => view()!.querySelector('textarea')!;
    const crumb = () => view()!.querySelector<HTMLButtonElement>('nav button')!;
    const viewDrafted = () =>
      Array.from(view()!.querySelectorAll('[data-drafted]')).map(
        (el) => el.querySelector('label')?.textContent,
      );
    const use = () => buttonByText('drafter.agent.prompt.use', view()!)!;

    it('opens the prompt it wrote in the view, and Use this prompt saves and sets it', async () => {
      mocks.createPrompt.mockImplementation(() => jsonResponse({ id: 'np1' }));
      drafter.scripts = [writes()];
      await render();
      await ask('A shipping agent for our website');
      // The view takes the main column; the form stays, hidden.
      expect(view()).not.toBeNull();
      expect(nameInput().closest('.hidden')).not.toBeNull();
      expect(view()!.textContent).toContain('agents.newAgent');
      expect(view()!.textContent).toContain('drafter.agent.prompt.newPrompt');
      expect(viewName().value).toBe('Shipping support');
      expect(viewText().value).toBe(PROMPT_TEXT);
      expect(viewDrafted()).toEqual([
        'modals.prompts.promptName',
        'modals.prompts.promptText',
      ]);
      // Nothing is created yet, and Next waits for the prompt.
      expect(mocks.createPrompt).not.toHaveBeenCalled();
      expect(panel()!.textContent).toContain('drafter.agent.prompt.wrote');
      expect(panel()!.textContent).toContain('drafter.agent.prompt.viewHint');
      expect(next()).toBeUndefined();
      expect(
        panel()!
          .querySelector('textarea[aria-label="drafter.askLabel"]')
          ?.getAttribute('placeholder'),
      ).toBe('drafter.agent.prompt.changePlaceholder');

      // The view's unsaved text goes with the next message, edits included.
      await act(async () => setNativeValue(viewText(), 'My own text.'));
      drafter.scripts = [writes('Friendlier text.')];
      await ask('Make it friendlier');
      expect(lastRequest().context.form.prompt_draft).toEqual({
        name: 'Shipping support',
        content: 'My own text.',
      });
      // A further prompt replaces the view's text, marked again.
      expect(viewText().value).toBe('Friendlier text.');
      expect(viewDrafted()).toContain('modals.prompts.promptText');

      await act(async () => use().click());
      expect(mocks.createPrompt.mock.calls).toEqual([
        [{ name: 'Shipping support', content: 'Friendlier text.' }, null],
      ]);
      // The list the pickers read now has it (the store is stubbed here).
      mockState.preference.prompts = [
        { id: 'default', name: 'default', type: 'public' },
        { id: 'np1', name: 'Shipping support', type: 'private' },
      ] as never[];
      // Back on the form with the prompt set and marked.
      expect(view()).toBeNull();
      expect(nameInput().closest('.hidden')).toBeNull();
      expect(drafted()).toContain('agents.form.sections.prompt');
      // The drawer says so and ends the turn with what it set and Next.
      const message = Array.from(
        panel()!.querySelectorAll('[data-item="message"]'),
      ).at(-1)!;
      expect(message.textContent).toBe('drafter.agent.prompt.saved');
      expect(
        message.compareDocumentPosition(next()!) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();

      // A change asked for afterwards updates the same prompt.
      drafter.scripts = [writes('Shorter text.')];
      await ask('Shorter');
      expect(view()!.textContent).toContain('Shipping support');
      expect(viewText().value).toBe('Shorter text.');
      await act(async () => use().click());
      expect(mocks.createPrompt).toHaveBeenCalledTimes(1);
      // At the version it was saved at.
      expect(mocks.updatePrompt.mock.calls[0][0]).toEqual({
        id: 'np1',
        name: 'Shipping support',
        content: 'Shorter text.',
        expected_updated_at: 'v1',
      });
      expect(
        container.querySelector('[data-slot="combobox-trigger"]')?.textContent,
      ).toContain('Shipping support');
      await act(async () => next()!.click());
      expect(lastRequest().context.step).toBe('safety');
      expect(lastRequest().context.form).toMatchObject({
        prompt_id: 'np1',
        prompt_draft: null,
      });
    });

    it('lists what a written prompt does to the one it replaces, as edits do', async () => {
      drafter.scripts = [
        [
          proposal({
            prompt: { ...WRITTEN, checks: ['citations_removed'] },
          }),
          { type: 'end' },
        ],
      ];
      await render();
      await ask('Write a prompt with no citations');
      expect(panel()!.textContent).toContain(
        'drafter.prompt.checks.citations_removed',
      );
      // The view's text goes back without the proposal's own keys.
      await ask('Shorter');
      expect(lastRequest().context.form.prompt_draft).toEqual({
        name: 'Shipping support',
        content: PROMPT_TEXT,
      });
    });

    it('keeps the prompt in the step on Back, then opens it again or keeps the old one', async () => {
      drafter.scripts = [writes()];
      await render();
      await ask('A shipping agent');
      await act(async () => crumb().click());
      expect(view()).toBeNull();
      const parked = () =>
        Array.from(
          panel()!.querySelectorAll('[data-slot="proposal-summary"]'),
        ).find((el) => el.textContent?.includes('drafter.agent.prompt.parked'));
      expect(parked()).toBeDefined();
      expect(next()).toBeUndefined();
      // An approval now isn't the step's Next: the prompt still waits.
      drafter.scripts = [
        [
          proposal({}, { steps: ['prompt'], next_step: 'safety' }),
          { type: 'end' },
        ],
      ];
      await ask('ok, next');
      expect(lastRequest().context.form.prompt_draft).toEqual({
        name: 'Shipping support',
        content: PROMPT_TEXT,
      });
      expect(drafter.requests).toHaveLength(2);
      expect(parked()).toBeDefined();

      await act(async () =>
        buttonByText('drafter.agent.prompt.open', parked()!)!.click(),
      );
      expect(viewText().value).toBe(PROMPT_TEXT);
      expect(viewDrafted()).toContain('modals.prompts.promptText');
      await act(async () => crumb().click());
      await act(async () =>
        buttonByText('drafter.agent.prompt.keep', parked()!)!.click(),
      );
      expect(parked()).toBeUndefined();
      expect(mocks.createPrompt).not.toHaveBeenCalled();
      await act(async () => next()!.click());
      expect(lastRequest().context.form).toMatchObject({
        prompt_id: 'default',
        prompt_draft: null,
      });
    });

    it('returns to the form on browser Back', async () => {
      drafter.scripts = [writes()];
      await render();
      await ask('A shipping agent');
      expect(probe.state).toMatchObject({ promptView: true });
      await act(async () => probe.navigate!(-1));
      expect(view()).toBeNull();
      expect(nameInput().closest('.hidden')).toBeNull();
      expect(panel()!.textContent).toContain('drafter.agent.prompt.parked');
    });
  });

  it('offers Continue on the step after an error', async () => {
    drafter.scripts = [
      [{ type: 'error', code: 'model_error' }, { type: 'end' }],
    ];
    await render();
    await ask('A shipping agent');
    const alert = panel()!.querySelector('[data-item="error"]')!;
    await act(async () =>
      buttonByText('drafter.agent.build.continueStep', alert)!.click(),
    );
    expect(lastRequest().messages.at(-1)).toEqual({
      role: 'user',
      content: 'drafter.agent.build.continue',
    });
    expect(lastRequest().context.step).toBe('basics');
  });

  it('notes a field edited in the form since the turn', async () => {
    drafter.scripts = [
      [
        proposal({ name: 'Shipping help' }, { steps: ['basics'] }),
        { type: 'end' },
      ],
    ];
    await render();
    await ask('Shipping agent');
    expect(panel()!.textContent).not.toContain('drafter.agent.formEdited');
    await act(async () => setNativeValue(nameInput(), 'My own name'));
    expect(panel()!.textContent).toContain('drafter.agent.formEdited');
    // Undo is no edit by hand.
    await act(async () => setNativeValue(nameInput(), 'Shipping help'));
    await act(async () => setNativeValue(nameInput(), ''));
    expect(panel()!.textContent).not.toContain('drafter.agent.formEdited');
  });

  it('steps the sheet aside on a phone and keeps the step in a strip', async () => {
    media.isMobile = true;
    media.isDesktop = false;
    drafter.scripts = [
      [
        proposal({ name: 'Shipping help' }, { steps: ['basics'] }),
        { type: 'end' },
      ],
    ];
    await render();
    await ask('Shipping agent');
    expect(nameInput().value).toBe('Shipping help');
    const strip = () =>
      container.querySelector<HTMLElement>('[data-slot="build-step-strip"]');
    expect(strip()).not.toBeNull();
    expect(strip()!.className).toContain('lg:hidden');
    expect(strip()!.textContent).toContain('drafter.agent.build.check');
    // The strip brings the sheet back.
    await act(async () =>
      buttonByText('drafter.agent.build.check', strip()!)!.click(),
    );
    expect(strip()).toBeNull();
    // Closed again, the strip is back; its Next runs the step's Next.
    await act(async () => wand()!.click());
    await act(async () =>
      buttonByText('drafter.agent.build.nextShort', strip()!)!.click(),
    );
    expect(lastRequest().context.step).toBe('knowledge');
  });

  // The picker's Add prompt and each row's Edit or View open the same
  // prompt view; Improve on its crumb row opens the drawer.
  {
    const PROMPTS = [
      { id: 'default', name: 'default', type: 'public' },
      { id: 'p1', name: 'Tone', type: 'private', access: 'owner' },
      { id: 'p2', name: 'Team tone', type: 'team', access: 'viewer' },
    ];
    beforeEach(() => {
      mockState.preference.prompts = PROMPTS as never[];
    });
    afterEach(() => {
      mockState.preference.prompts = [];
      mocks.getSinglePrompt.mockClear();
      mocks.updatePrompt.mockClear();
    });

    const view = () =>
      container.querySelector<HTMLElement>('[data-slot="prompt-view"]');
    const viewText = () => view()!.querySelector('textarea')!;
    const save = () => buttonByText('modals.prompts.save', view()!);
    // The crumb row's wand: Draft on a new agent, Improve on a saved one.
    const viewWand = () =>
      view()!.querySelector<HTMLButtonElement>('[data-drafter-entry]');
    const promptTrigger = () =>
      Array.from(
        container.querySelectorAll<HTMLButtonElement>(
          '[data-slot="combobox-trigger"]',
        ),
      ).find(
        (button) =>
          button.closest('[data-slot="form-field"]')?.querySelector('label')
            ?.textContent === 'agents.form.sections.prompt',
      )!;
    /** Open the Prompt picker and press a row's Edit or View. */
    const openFromRow = async (id: string) => {
      const trigger = promptTrigger();
      await act(async () => {
        trigger.dispatchEvent(
          new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
        );
        trigger.click();
      });
      await act(async () =>
        document.body
          .querySelector<HTMLButtonElement>(
            `[cmdk-item][data-value="${id}"] [data-slot="combobox-row-action"]`,
          )!
          .click(),
      );
    };

    const renderWithPrompt = async (promptId: string) => {
      mocks.getAgent.mockImplementation(() =>
        jsonResponse({
          id: 'agent-1',
          name: 'Deal Desk',
          description: 'Researches deals',
          status: 'draft',
          agent_type: 'research',
          prompt_id: promptId,
          access: 'owner',
        }),
      );
      await act(async () => {
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
    };

    it('edits an own prompt in the view and saves it', async () => {
      await renderWithPrompt('p1');
      await openFromRow('p1');
      expect(mocks.getSinglePrompt).toHaveBeenCalledWith('p1', null);
      expect(view()!.textContent).toContain('Deal Desk');
      expect(view()!.textContent).toContain('Tone');
      expect(viewText().value).toBe('Text of p1');
      await act(async () => setNativeValue(viewText(), 'Shorter.'));
      await act(async () => save()!.click());
      expect(mocks.updatePrompt.mock.calls[0][0]).toEqual({
        id: 'p1',
        name: 'Tone',
        content: 'Shorter.',
        expected_updated_at: 'v1',
      });
      expect(view()).toBeNull();
    });

    it('opens a prompt from its picker row without picking it', async () => {
      await renderWithPrompt('p1');
      await openFromRow('default');
      expect(document.body.querySelector('[cmdk-list]')).toBeNull();
      // A built-in opens read-only.
      expect(mocks.getSinglePrompt).toHaveBeenCalledWith('default', null);
      expect(viewText().value).toBe('Text of default');
      expect(viewText().readOnly).toBe(true);
      // Back on the form, the agent still has its prompt.
      await act(async () =>
        view()!.querySelector<HTMLButtonElement>('nav button')!.click(),
      );
      expect(view()).toBeNull();
      expect(promptTrigger().textContent).toContain('Tone');
    });

    it('asks before leaving the view with unsaved text', async () => {
      await renderWithPrompt('p1');
      await openFromRow('p1');
      await act(async () => setNativeValue(viewText(), 'Shorter.'));
      await act(async () =>
        view()!.querySelector<HTMLButtonElement>('nav button')!.click(),
      );
      expect(view()).not.toBeNull();
      // Save and leave.
      await act(async () =>
        document
          .querySelector<HTMLButtonElement>('[data-testid="confirm-delete"]')!
          .click(),
      );
      await act(async () => {
        await mocks.submitResult;
      });
      expect(mocks.updatePrompt).toHaveBeenCalledTimes(1);
      expect(view()).toBeNull();
    });

    it("keeps the leave dialog open with the reason when the prompt can't be saved", async () => {
      await renderWithPrompt('p1');
      await openFromRow('p1');
      await act(async () =>
        setNativeValue(
          view()!.querySelector<HTMLInputElement>('input[type="text"]')!,
          '',
        ),
      );
      await act(async () =>
        view()!.querySelector<HTMLButtonElement>('nav button')!.click(),
      );
      await act(async () =>
        document
          .querySelector<HTMLButtonElement>('[data-testid="confirm-delete"]')!
          .click(),
      );
      await expect(mocks.submitResult).rejects.toThrow('name');
      expect(mocks.updatePrompt).not.toHaveBeenCalled();
      expect(
        document.querySelector('[data-testid="confirm-delete"]'),
      ).not.toBeNull();
      expect(view()).not.toBeNull();
    });

    it("keeps the page's history state when Back asks about unsaved text", async () => {
      mocks.getAgent.mockImplementation(() =>
        jsonResponse({
          id: 'agent-1',
          name: 'Deal Desk',
          description: 'Researches deals',
          status: 'draft',
          prompt_id: 'p1',
          access: 'owner',
        }),
      );
      await act(async () => {
        root.render(
          <MemoryRouter
            initialEntries={[
              { pathname: '/agents/edit/agent-1', state: { from: 'list' } },
            ]}
          >
            <Routes>
              <Route
                path="/agents/edit/:agentId"
                element={<NewAgent mode="edit" />}
              />
            </Routes>
            <RouterProbe />
          </MemoryRouter>,
        );
      });
      await openFromRow('p1');
      await act(async () => setNativeValue(viewText(), 'Shorter.'));
      await act(async () => probe.navigate!(-1));
      // Put back while it asks, with what the entry held.
      expect(view()).not.toBeNull();
      expect(probe.state).toEqual({ from: 'list', promptView: true });
    });

    it('stays on the prompt, without scrolling the form, when Show in agent asks first', async () => {
      await renderWithPrompt('p1');
      await openFromRow('p1');
      await act(async () => setNativeValue(viewText(), 'Shorter.'));
      drafter.scripts = [
        [proposal({ starters: ['Where is my deal?'] }), { type: 'end' }],
      ];
      await ask('Add a starter');
      const scroll = vi
        .spyOn(Element.prototype, 'scrollIntoView')
        .mockImplementation(() => undefined);
      await act(async () =>
        buttonByText('drafter.agent.showInAgent', panel()!)!.click(),
      );
      await act(() => new Promise((resolve) => requestAnimationFrame(resolve)));
      expect(view()).not.toBeNull();
      expect(scroll).not.toHaveBeenCalled();
      scroll.mockRestore();
    });

    it('improves an own prompt with the drawer, filling the view instead of creating one', async () => {
      await renderWithPrompt('p1');
      await openFromRow('p1');
      await act(async () => buttonByText('drafter.improve', view()!)!.click());
      expect(view()).not.toBeNull();
      expect(panel()).not.toBeNull();
      expect(
        buttonByText('drafter.improve', view()!)!.getAttribute('aria-expanded'),
      ).toBe('true');
      drafter.scripts = [
        [
          proposal({
            prompt: { kind: 'new', name: 'Other', content: 'Tighter.' },
          }),
          { type: 'end' },
        ],
      ];
      await ask('Tighten it');
      // The open prompt's text goes along, with the id of the prompt it is.
      expect(lastRequest().context.form.prompt_draft).toEqual({
        id: 'p1',
        name: 'Tone',
        content: 'Text of p1',
      });
      // A saved prompt keeps its name; the text is drafted.
      expect(
        view()!.querySelector<HTMLInputElement>('input[type="text"]')!.value,
      ).toBe('Tone');
      expect(viewText().value).toBe('Tighter.');
      expect(mocks.createPrompt).not.toHaveBeenCalled();
      await ask('More');
      // The view's unsaved text changes the saved prompt it came from.
      expect(lastRequest().context.form.prompt_draft).toEqual({
        id: 'p1',
        name: 'Tone',
        content: 'Tighter.',
      });
    });

    it('improves the prompt opened from a picker row, not the one the agent uses', async () => {
      mockState.preference.prompts = [
        ...PROMPTS,
        { id: 'p3', name: 'Formal', type: 'private', access: 'owner' },
      ] as never[];
      await renderWithPrompt('p1');
      await openFromRow('p3');
      drafter.scripts = [
        [
          proposal({
            prompt: { kind: 'new', name: 'Other', content: 'Formal, shorter.' },
          }),
          { type: 'end' },
        ],
      ];
      await ask('Shorter');
      // The drafter reads the prompt on screen, unchanged as it is.
      expect(lastRequest().context.form).toMatchObject({
        prompt_id: 'p1',
        prompt_draft: { id: 'p3', name: 'Formal', content: 'Text of p3' },
      });
      expect(viewText().value).toBe('Formal, shorter.');
      await act(async () => save()!.click());
      expect(mocks.updatePrompt.mock.calls[0][0]).toMatchObject({
        id: 'p3',
        content: 'Formal, shorter.',
      });
    });

    it('opens a rewrite that lands after another prompt opened as a new prompt, leaving that one alone', async () => {
      mockState.preference.prompts = [
        ...PROMPTS,
        { id: 'p3', name: 'Formal', type: 'private', access: 'owner' },
      ] as never[];
      await renderWithPrompt('p1');
      await openFromRow('p1');
      let land: (events: unknown[]) => void = () => undefined;
      drafter.scripts = [
        new Promise((resolve) => {
          land = resolve;
        }),
      ];
      await ask('Rewrite it');
      expect(lastRequest().context.form.prompt_draft).toMatchObject({
        id: 'p1',
      });
      // Back on the form, then another prompt opened before the turn ends.
      await act(async () =>
        view()!.querySelector<HTMLButtonElement>('nav button')!.click(),
      );
      await openFromRow('p3');
      await act(async () =>
        land([
          proposal({
            prompt: { kind: 'new', name: 'Rewrite', content: 'Rewritten.' },
          }),
          { type: 'end' },
        ]),
      );
      // The rewrite opens as a prompt of its own; Formal is untouched.
      expect(view()!.textContent).toContain('drafter.agent.prompt.newPrompt');
      expect(viewText().value).toBe('Rewritten.');
      await act(async () =>
        buttonByText('drafter.agent.prompt.use', view()!)!.click(),
      );
      expect(mocks.updatePrompt).not.toHaveBeenCalled();
      expect(mocks.createPrompt.mock.calls[0][0]).toEqual({
        name: 'Rewrite',
        content: 'Rewritten.',
      });
    });

    it('keeps the unsaved text of another prompt opened before a rewrite lands', async () => {
      mockState.preference.prompts = [
        ...PROMPTS,
        { id: 'p3', name: 'Formal', type: 'private', access: 'owner' },
      ] as never[];
      await renderWithPrompt('p1');
      await openFromRow('p1');
      let land: (events: unknown[]) => void = () => undefined;
      drafter.scripts = [
        new Promise((resolve) => {
          land = resolve;
        }),
      ];
      await ask('Rewrite it');
      await act(async () =>
        view()!.querySelector<HTMLButtonElement>('nav button')!.click(),
      );
      await openFromRow('p3');
      await act(async () => setNativeValue(viewText(), 'My formal text.'));
      await act(async () =>
        land([
          proposal({
            prompt: { kind: 'new', name: 'Rewrite', content: 'Rewritten.' },
          }),
          { type: 'end' },
        ]),
      );
      // Formal stays open with what the user typed; the rewrite waits.
      expect(
        view()!.querySelector<HTMLInputElement>('input[type="text"]')!.value,
      ).toBe('Formal');
      expect(viewText().value).toBe('My formal text.');
      await act(async () => save()!.click());
      expect(mocks.updatePrompt.mock.calls[0][0]).toMatchObject({
        id: 'p3',
        content: 'My formal text.',
      });
      expect(panel()!.textContent).toContain('drafter.agent.prompt.parked');
    });

    it('opens a prompt it wrote in a view of its own, never in a read-only one', async () => {
      await renderWithPrompt('p1');
      // The drawer open on the form, then a team prompt opened to read.
      await act(async () => wand()!.click());
      await openFromRow('p2');
      drafter.scripts = [
        [
          proposal({
            prompt: { kind: 'new', name: 'Warm tone', content: 'Be warm.' },
          }),
          { type: 'end' },
        ],
      ];
      await ask('Warmer');
      expect(lastRequest().context.form.prompt_draft).toEqual({
        id: 'p2',
        name: 'Team tone',
        content: 'Text of p2',
      });
      // A new prompt to use, with its Save: the team's prompt is untouched.
      expect(viewText().readOnly).toBe(false);
      expect(viewText().value).toBe('Be warm.');
      expect(view()!.textContent).toContain('drafter.agent.prompt.newPrompt');
      expect(buttonByText('drafter.agent.prompt.use', view()!)).toBeDefined();
    });

    const promptEdits = (
      edits: { id: string; find: string; replace: string; reason: string }[],
    ) => [
      proposal({ prompt: { kind: 'edit', id: 'p1', edits, checks: [] } }),
      { type: 'end' },
    ];
    const review = () =>
      view()?.querySelector<HTMLElement>('[data-slot="prompt-review"]') ?? null;

    it("reviews changes to the agent's own prompt in its view, then saves it", async () => {
      await renderWithPrompt('p1');
      drafter.scripts = [
        promptEdits([
          { id: 'e1', find: 'Text', replace: 'Words', reason: 'Plainer.' },
          {
            id: 'e2',
            find: 'of p1',
            replace: 'for p1',
            reason: 'Reads better.',
          },
        ]),
      ];
      await ask('Make the prompt plainer');
      // The saved prompt opens with its own text, and the drawer stays the agent's.
      expect(mocks.getSinglePrompt).toHaveBeenCalledWith('p1', null);
      expect(view()).not.toBeNull();
      expect(review()).not.toBeNull();
      expect(review()!.querySelectorAll('[data-change-id]')).toHaveLength(2);
      expect(panel()!.textContent).toContain('drafter.agent.prompt.changes');
      expect(panel()!.textContent).toContain('drafter.agent.prompt.reviewHint');
      // Save waits for the review.
      expect(save()!.disabled).toBe(true);
      await act(async () =>
        buttonByText(
          'drafter.prompt.reject',
          review()!.querySelector('[data-change-id="e2"]')!,
        )!.click(),
      );
      await act(async () =>
        buttonByText('drafter.prompt.acceptAll', panel()!)!.click(),
      );
      expect(review()).toBeNull();
      expect(viewText().value).toBe('Words of p1');
      expect(
        buttonByText('drafter.prompt.acceptAll', panel()!),
      ).toBeUndefined();
      await act(async () => save()!.click());
      expect(mocks.updatePrompt.mock.calls[0][0]).toEqual({
        id: 'p1',
        name: 'Tone',
        content: 'Words of p1',
        expected_updated_at: 'v1',
      });
      expect(mocks.createPrompt).not.toHaveBeenCalled();
      expect(view()).toBeNull();
    });

    it('ends an open review with the choices so far on a new request, and Discard keeps the text', async () => {
      await renderWithPrompt('p1');
      drafter.scripts = [
        promptEdits([
          { id: 'e1', find: 'Text', replace: 'Words', reason: 'Plainer.' },
          {
            id: 'e2',
            find: 'of p1',
            replace: 'for p1',
            reason: 'Reads better.',
          },
        ]),
        promptEdits([
          { id: 'e1', find: 'of p1', replace: 'about p1', reason: 'Clearer.' },
        ]),
      ];
      await ask('Make the prompt plainer');
      await act(async () =>
        review()!
          .querySelector<HTMLButtonElement>(
            '[data-change-id="e1"] [data-action="accept"]',
          )!
          .click(),
      );
      await ask('Something else too');
      // The accepted change went along as the view's text.
      expect(lastRequest().context.form.prompt_draft).toEqual({
        id: 'p1',
        name: 'Tone',
        content: 'Words of p1',
      });
      expect(review()!.querySelectorAll('[data-change-id]')).toHaveLength(1);
      await act(async () =>
        buttonByText('drafter.prompt.discard', panel()!)!.click(),
      );
      expect(review()).toBeNull();
      expect(viewText().value).toBe('Words of p1');
    });

    it('offers Show in agent when a turn changes the form behind the prompt view', async () => {
      await renderWithPrompt('p1');
      await openFromRow('p1');
      drafter.scripts = [
        [proposal({ starters: ['Where is my deal?'] }), { type: 'end' }],
        [
          proposal({ starters: ['Where is my deal?', 'Rates?'] }),
          { type: 'end' },
        ],
      ];
      await ask('Add a starter');
      const show = buttonByText('drafter.agent.showInAgent', panel()!)!;
      expect(show).toBeDefined();
      await act(async () => show.click());
      expect(view()).toBeNull();
      // On the form, nothing to show.
      await ask('Another one');
      expect(
        buttonByText('drafter.agent.showInAgent', panel()!),
      ).toBeUndefined();
    });

    it('waits for an open review before an approval moves the build on', async () => {
      await render();
      drafter.scripts = [
        [
          proposal(
            { name: 'Deal Desk', prompt: { kind: 'existing', id: 'p1' } },
            { steps: ['basics'] },
          ),
          { type: 'end' },
        ],
        [
          ...promptEdits([
            { id: 'e1', find: 'Text', replace: 'Words', reason: 'Plainer.' },
          ]).slice(0, 1),
          // The same turn approves the step while the review is open.
          proposal({}, { steps: ['basics'], next_step: 'knowledge' }),
          { type: 'end' },
        ],
      ];
      await ask('A deal desk on my Tone prompt');
      await ask('Plainer prompt, then go on');
      expect(review()).not.toBeNull();
      expect(drafter.requests).toHaveLength(2);
      // The drawer's latest turn offers the review's actions.
      await act(async () =>
        buttonByText('drafter.prompt.acceptAll', panel()!)!.click(),
      );
      expect(viewText().value).toBe('Words of p1');
      // Once it is decided, the approval moves on.
      expect(drafter.requests).toHaveLength(3);
      expect(lastRequest().context.step).toBe('knowledge');
    });

    it('drops changes that waited for a prompt the view never loaded', async () => {
      await renderWithPrompt('p1');
      mocks.getSinglePrompt.mockImplementationOnce(() =>
        jsonResponse({}, false),
      );
      drafter.scripts = [
        promptEdits([
          { id: 'e1', find: 'Text', replace: 'Words', reason: 'Plainer.' },
        ]),
      ];
      await ask('Make the prompt plainer');
      expect(review()).toBeNull();
      await act(async () =>
        view()!.querySelector<HTMLButtonElement>('nav button')!.click(),
      );
      expect(view()).toBeNull();
      // Opened later on its own, the prompt shows no stale review.
      await openFromRow('p1');
      expect(viewText().value).toBe('Text of p1');
      expect(review()).toBeNull();
    });

    it('counts only the changes that fit the saved text, and says how many did not', async () => {
      await renderWithPrompt('p1');
      drafter.scripts = [
        promptEdits([
          { id: 'e1', find: 'Text', replace: 'Words', reason: 'Plainer.' },
          { id: 'e2', find: 'Not there', replace: 'x', reason: 'r' },
        ]),
      ];
      await ask('Make the prompt plainer');
      expect(review()!.querySelectorAll('[data-change-id]')).toHaveLength(1);
      expect(panel()!.textContent).toContain('drafter.agent.prompt.unfit');
    });

    it('reviews changes to a prompt saved with Windows line ends', async () => {
      mocks.getSinglePrompt.mockImplementationOnce(() =>
        jsonResponse({ content: 'Be brief.\r\nBe kind.', updated_at: 'v1' }),
      );
      await renderWithPrompt('p1');
      drafter.scripts = [
        promptEdits([
          {
            id: 'e1',
            find: 'brief.\nBe',
            replace: 'short.\nBe',
            reason: 'Plainer.',
          },
        ]),
      ];
      await ask('Plainer');
      expect(review()).not.toBeNull();
      expect(panel()!.textContent).not.toContain(
        'drafter.agent.prompt.editsStale',
      );
    });

    it('says so when none of the changes fit the saved text', async () => {
      await renderWithPrompt('p1');
      drafter.scripts = [
        promptEdits([
          { id: 'e1', find: 'Not there', replace: 'x', reason: 'r' },
        ]),
      ];
      await ask('Make the prompt plainer');
      expect(view()).not.toBeNull();
      expect(review()).toBeNull();
      expect(viewText().value).toBe('Text of p1');
      expect(panel()!.textContent).toContain('drafter.agent.prompt.editsStale');
    });

    it("shows a prompt the caller can't edit read-only, and improves a copy", async () => {
      await renderWithPrompt('p2');
      await openFromRow('p2');
      expect(viewText().readOnly).toBe(true);
      expect(save()).toBeUndefined();
      // Improve on the crumb row makes the copy.
      await act(async () => buttonByText('drafter.improve', view()!)!.click());
      expect(
        view()!.querySelector<HTMLInputElement>('input[type="text"]')!.value,
      ).toBe('Team tone copy');
      expect(viewText().value).toBe('Text of p2');
      expect(save()).toBeDefined();
      expect(panel()).not.toBeNull();
    });

    it('improves a copy of a built-in, and saving picks the copy', async () => {
      mockState.preference.prompts = [
        ...PROMPTS,
        { id: 'p-new', name: 'default copy', type: 'private', access: 'owner' },
      ] as never[];
      mocks.createPrompt.mockImplementation(() =>
        jsonResponse({ id: 'p-new' }),
      );
      await render();
      await openFromRow('default');
      await act(async () => viewWand()!.click());
      expect(mocks.getSinglePrompt).toHaveBeenCalledWith('default', null);
      expect(view()!.textContent).toContain('modals.prompts.duplicatePrompt');
      expect(panel()).not.toBeNull();
      // "default copy" is listed already: the name has to change first.
      const name =
        view()!.querySelector<HTMLInputElement>('input[type="text"]')!;
      await act(async () => setNativeValue(name, 'Mine'));
      await act(async () => save()!.click());
      expect(mocks.createPrompt.mock.calls[0][0]).toEqual({
        name: 'Mine',
        content: 'Text of default',
      });
      expect(view()).toBeNull();
      expect(
        container.querySelector('[data-slot="combobox-trigger"]')?.textContent,
      ).toContain('default copy');
    });

    it("adds a prompt from the picker's footer in the view", async () => {
      mocks.createPrompt.mockImplementation(() => jsonResponse({ id: 'p1' }));
      await render();
      const trigger = container.querySelector<HTMLButtonElement>(
        '[data-slot="combobox-trigger"]',
      )!;
      await act(async () => {
        trigger.dispatchEvent(
          new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
        );
        trigger.click();
      });
      await act(async () =>
        Array.from(document.body.querySelectorAll('button'))
          .find((b) => b.textContent === 'settings.prompts.addPrompt')!
          .click(),
      );
      expect(view()!.textContent).toContain('modals.prompts.addPrompt');
      expect(save()!.disabled).toBe(true);
      await act(async () =>
        setNativeValue(
          view()!.querySelector<HTMLInputElement>('input[type="text"]')!,
          'Brand voice',
        ),
      );
      await act(async () => setNativeValue(viewText(), 'Be brief.'));
      await act(async () => save()!.click());
      expect(mocks.createPrompt.mock.calls[0][0]).toEqual({
        name: 'Brand voice',
        content: 'Be brief.',
      });
      expect(
        container.querySelector('[data-slot="combobox-trigger"]')?.textContent,
      ).toContain('Tone');
    });

    it('offers no Improve while the drafter is off', async () => {
      drafter.config = { enabled: false, model: null, reason: null };
      await render();
      await openFromRow('default');
      expect(view()).not.toBeNull();
      expect(viewWand()).toBeNull();
    });
  }
});
