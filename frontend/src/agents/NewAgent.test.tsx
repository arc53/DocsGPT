import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import type { MultiSelectPopoverItem } from '../components/MultiSelectPopover';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
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
    dispatch: vi.fn(),
    getAgent: vi.fn(() => jsonResponse({})),
    createAgent: vi.fn(() => jsonResponse({ message: 'Name is taken' }, false)),
    tools: null as unknown[] | null,
    connections: [] as unknown[],
    catalog: [] as unknown[],
    deleteAgent: vi.fn(() => jsonResponse({})),
    guardrailsProps: vi.fn(),
  };
});
const { jsonResponse } = mocks;

vi.mock('../connectors/SignInAgainNotice', () => ({
  default: () => null,
  useSignInAgain: () => ({ reconnect: vi.fn(), modals: null }),
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(mockState),
  useDispatch: () => mocks.dispatch,
}));

vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: () =>
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
    createAgent: mocks.createAgent,
    updateAgent: () => jsonResponse({}),
    deleteAgent: mocks.deleteAgent,
    createPrompt: () => jsonResponse({}),
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
    getModels: () => jsonResponse({ models: [] }),
    transformModels: () => [],
  },
}));

// The pickers render only their trigger here, plus each item's rich
// description so the device status pill can be checked.
vi.mock('../components/MultiSelectPopover', () => ({
  MultiSelectPopover: ({
    trigger,
    items,
  }: {
    trigger: React.ReactNode;
    items: MultiSelectPopoverItem[];
  }) => (
    <div data-testid="picker">
      {trigger}
      {items.map((item) => (
        <div key={item.id} data-group={item.group}>
          {item.descriptionNode}
        </div>
      ))}
    </div>
  ),
}));

vi.mock('./workflow/WorkflowBuilder', () => ({ default: () => null }));
vi.mock('./AgentPreview', () => ({ default: () => null }));
vi.mock('../settings/Prompts', () => ({ default: () => null }));
vi.mock('./components/GuardrailsSection', () => ({
  default: (props: { disabled?: boolean }) => {
    mocks.guardrailsProps(props);
    return null;
  },
  guardrailsIncomplete: () => false,
}));
vi.mock('../upload/Upload', () => ({ default: () => null }));
vi.mock('../modals/AgentDetailsModal', () => ({ default: () => null }));
vi.mock('../teams/ShareToTeamModal', () => ({ default: () => null }));
vi.mock('../modals/ConfirmationModal', () => ({
  default: ({
    modalState,
    handleSubmit,
  }: {
    modalState: string;
    handleSubmit: () => void;
  }) =>
    modalState === 'ACTIVE' ? (
      <button type="button" data-testid="confirm-delete" onClick={handleSubmit}>
        confirm
      </button>
    ) : null,
}));
vi.mock('../preferences/PromptsModal', () => ({ default: () => null }));
vi.mock('../navigation/SectionPills', () => ({
  default: () => <div data-testid="section-pills" />,
}));
vi.mock('../navigation/SectionPageHeader', () => ({
  CurrentSectionHeader: ({
    title,
    titleAction,
  }: {
    title?: React.ReactNode;
    titleAction?: React.ReactNode;
  }) => (
    <div>
      {title ? <h1>{title}</h1> : null}
      {titleAction}
    </div>
  ),
}));
vi.mock('../components/FileUpload', () => ({ FileUpload: () => null }));
vi.mock('../components/SourcesPopoverFooter', () => ({ default: () => null }));
vi.mock('../components/ToolIcon', () => ({ default: () => null }));

import NewAgent from './NewAgent';

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
    mocks.tools = null;
    mocks.connections = [];
    mocks.catalog = [];
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

  // Decision 63 (3): every field, picker and button in the form is 42px.
  it('renders the name field as a default-size (42px) pill Input', async () => {
    await render();
    const name = container.querySelector<HTMLInputElement>(
      'input[placeholder="agents.form.placeholders.agentName"]',
    )!;
    expect(name.getAttribute('data-slot')).toBe('input');
    expect(name.getAttribute('data-size')).toBe('default');
    expect(name.getAttribute('data-shape')).toBe('pill');
  });

  it('renders the Add prompt button at the field height', async () => {
    await render();
    const add = buttonByText('agents.form.buttons.add');
    expect(add.getAttribute('data-variant')).toBe('outline-primary');
    expect(add.getAttribute('data-size')).toBe('field');
    expect(add.getAttribute('data-shape')).toBe('pill');
  });

  it('renders the token and request limits as default-size pill Inputs', async () => {
    await render();
    await act(async () =>
      buttonByText('agents.form.sections.advanced').click(),
    );
    for (const key of ['enterTokenLimit', 'enterRequestLimit']) {
      const field = container.querySelector(
        `input[placeholder="agents.form.placeholders.${key}"]`,
      )!;
      expect(field.getAttribute('data-size')).toBe('default');
      expect(field.getAttribute('data-shape')).toBe('pill');
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
      .closest('[data-slot="form-field"]')!;
    expect(description.className).toContain('col-span-2');
    expect(description.className).toContain('sm:col-start-2');
  });

  it('lists tool groups as built-in, default, one per connection, then custom', async () => {
    mocks.tools = [
      { id: 'custom', name: 'api_tool', display_name: 'My API' },
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
      'agents.form.toolsPopup.groupBuiltin',
      'agents.form.toolsPopup.groupDefault',
      'agents.form.toolsPopup.groupConnection',
      'agents.form.toolsPopup.groupCustom',
    ]);
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
    expect(groups).toEqual(['Telegram', 'agents.form.toolsPopup.groupCustom']);
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

  it('offers Preview from the title-row menu until the agent is published', async () => {
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
    // Beside the page title, not in the toolbar row.
    expect(menu.closest('[data-slot="page-toolbar"]')).toBeNull();
    expect(menu.parentElement!.querySelector('h1')).not.toBeNull();
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

  it('stretches the main button on a phone', async () => {
    await render();
    const publish = buttonByText('agents.form.buttons.publish');
    expect(publish.className).toContain('flex-1');
    expect(publish.className).toContain('sm:flex-none');
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

  it('renders the description as a large ui Textarea', async () => {
    await render();
    const description = container.querySelector(
      'textarea[placeholder="agents.form.placeholders.describeAgent"]',
    )!;
    expect(description.getAttribute('data-slot')).toBe('textarea');
    expect(description.getAttribute('data-size')).toBe('lg');
  });

  it('renders the pickers as pill comboboxes, muted while empty', async () => {
    await render();
    const triggers = Array.from(
      container.querySelectorAll('[data-testid="picker"] > button'),
    );
    // Sources, tools, models.
    expect(triggers).toHaveLength(3);
    for (const trigger of triggers) {
      expect(trigger.getAttribute('data-variant')).toBe('combobox');
      expect(trigger.getAttribute('data-size')).toBe('field');
      expect(trigger.getAttribute('data-shape')).toBe('pill');
      expect(trigger.hasAttribute('data-placeholder')).toBe(true);
      expect(trigger.querySelector('span.truncate')).not.toBeNull();
    }
  });

  it('shows the device status as a Badge', async () => {
    await render();
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
    expect(alert.querySelector('svg.lucide-circle-x')).not.toBeNull();
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
    expect(schema.getAttribute('data-size')).toBe('lg');

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

  it('gives the owner Share, Access details and the danger zone', async () => {
    await renderEdit('owner', OWNER);
    expect(buttonByText('agents.form.dangerZone.deleteButton')).toBeDefined();
    expect(await menuLabels()).toEqual([
      'agents.form.buttons.accessDetails',
      'agents.shareWithTeam',
    ]);
  });

  it('hides Share and Delete from an editor but keeps Access details', async () => {
    await renderEdit('editor', EDITOR);
    expect(buttonByText('agents.form.dangerZone.deleteButton')).toBeUndefined();
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

  it('hides Access details without manage_access_details', async () => {
    await renderEdit(
      'editor',
      EDITOR.filter((a) => a !== 'manage_access_details'),
    );
    expect(await menuLabels()).toEqual([]);
  });

  it('reports a failed delete in a toast instead of throwing', async () => {
    mocks.deleteAgent.mockImplementation(() =>
      jsonResponse({ message: 'Only the owner can delete' }, false),
    );
    await renderEdit('owner', OWNER);
    await act(async () =>
      buttonByText('agents.form.dangerZone.deleteButton')!.click(),
    );
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-testid="confirm-delete"]')!
        .click(),
    );
    expect(mocks.dispatch).toHaveBeenCalledWith({
      type: 'actionToast/showActionToast',
      payload: { variant: 'destructive', message: 'Only the owner can delete' },
    });
  });
});
