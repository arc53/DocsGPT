import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// A name is shown after its key, escaped the way i18next does unless the
// call turns escaping off (React escapes it already).
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (
      key: string,
      options?: { name?: string; interpolation?: { escapeValue?: boolean } },
    ) => {
      if (options?.name === undefined) return key;
      const name =
        options.interpolation?.escapeValue === false
          ? options.name
          : options.name.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
      return `${key}:${name}`;
    },
  }),
}));

const folderList = (items: unknown[]) => ({
  items,
  loaded: true,
  loading: false,
  failed: false,
  latestRequestId: null,
  removedParents: {},
});
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({
      preference: {
        token: 'token',
        sourceDocs: [{ id: 'd-1', name: 'Rate sheets' }],
      },
      folders: {
        tree: folderList([
          { id: 'f-1', name: 'Carriers', parent_id: null },
          { id: 'f-2', name: 'Rate archive', parent_id: 'f-1' },
        ]),
      },
    }),
  useDispatch: () => vi.fn(),
}));

vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }));

// The picker is exercised through its onDrop handler: happy-dom can't drive a
// real drag or a file chooser, and the drop is what stages the YAML.
const dropzone = vi.hoisted(() => ({
  onDrop: null as null | ((accepted: File[], rejected: unknown[]) => void),
}));
vi.mock('react-dropzone', () => ({
  useDropzone: (options: {
    onDrop: (accepted: File[], rejected: unknown[]) => void;
  }) => {
    dropzone.onDrop = options.onDrop;
    return {
      getRootProps: () => ({}),
      getInputProps: () => ({}),
      isDragActive: false,
      isDragReject: false,
    };
  },
}));

const service = vi.hoisted(() => ({
  planImportAgent: vi.fn(),
  importAgent: vi.fn(),
}));
vi.mock('../api/services/userService', () => ({ default: service }));

import ImportAgentModal from './ImportAgentModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const jsonResponse = (body: unknown) =>
  ({ ok: true, json: async () => body }) as Response;

const flush = () => act(async () => new Promise((r) => setTimeout(r, 0)));

const clickButton = async (label: string) => {
  const button = Array.from(document.querySelectorAll('button')).find(
    (b) => b.textContent === label,
  );
  expect(button).toBeDefined();
  await act(async () => button!.click());
  await flush();
};

describe('ImportAgentModal', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    service.planImportAgent.mockResolvedValue(
      jsonResponse({
        success: true,
        plan: {
          target: { action: 'create', agent_id: null, matched_by: null },
          sources: [],
          tools: [],
          prompt: { status: 'default' },
          models: [],
        },
      }),
    );
    service.importAgent.mockResolvedValue(
      jsonResponse({
        success: true,
        agent_id: 'agent-1',
        agent_type: 'classic',
        status: 'draft',
        warnings: [
          "Source 'Carrier Rate Cards' not found; left unattached",
          "Model 'gpt-4o' not available; skipped",
        ],
      }),
    );
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
  });

  it('shows post-import warnings as a polite warning alert', async () => {
    act(() => {
      root.render(
        <ImportAgentModal
          modalState="ACTIVE"
          setModalState={() => undefined}
        />,
      );
    });

    const file = new File(['name: Agent\n'], 'agent.yaml', {
      type: 'application/x-yaml',
    });
    await act(async () => dropzone.onDrop!([file], []));
    await flush();
    await clickButton('modals.importAgent.review');
    await clickButton('modals.importAgent.import');

    const notice = document.querySelector('[role="status"]');
    expect(notice).not.toBeNull();
    expect(notice!.className).toContain('bg-warning/10');
    expect(notice!.className).toContain('text-warning');
    expect(notice!.querySelector('svg')?.getAttribute('aria-hidden')).toBe(
      'true',
    );
    expect(notice!.querySelector('h5')?.textContent).toBe(
      'modals.importAgent.warningsTitle',
    );
    const items = Array.from(notice!.querySelectorAll('ul > li')).map(
      (li) => li.textContent,
    );
    expect(items).toEqual([
      "Source 'Carrier Rate Cards' not found; left unattached",
      "Model 'gpt-4o' not available; skipped",
    ]);
    expect(document.querySelector('[role="alert"]')).toBeNull();
  });
  it('draws plan warnings and a failed import as Alerts', async () => {
    service.planImportAgent.mockResolvedValue(
      jsonResponse({
        success: true,
        plan: {
          target: { action: 'update', agent_id: 'a1', matched_by: 'name' },
          workflow: { action: 'delete', nodes: 3 },
          sources: [],
          tools: [{ key: 't1', type: 'brave', status: 'unavailable' }],
          prompt: { status: 'default' },
          models: [],
        },
      }),
    );
    service.importAgent.mockResolvedValue(
      jsonResponse({ success: false, message: 'Import blew up' }),
    );
    act(() => {
      root.render(
        <ImportAgentModal
          modalState="ACTIVE"
          setModalState={() => undefined}
        />,
      );
    });

    const file = new File(['name: Agent\n'], 'agent.yaml', {
      type: 'application/x-yaml',
    });
    await act(async () => dropzone.onDrop!([file], []));
    await flush();
    await clickButton('modals.importAgent.review');

    const warnings = Array.from(
      document.querySelectorAll('[data-slot="alert"][data-variant="warning"]'),
    ).map((a) => a.textContent);
    expect(warnings).toEqual([
      'modals.importAgent.workflowDelete',
      'modals.importAgent.toolUnavailable',
    ]);
    // The target line is a static note: an info Alert, not announced.
    const note = document.querySelector(
      '[data-slot="alert"][data-variant="info"]',
    );
    expect(note?.getAttribute('role')).toBe('note');
    expect(note?.textContent).toContain('modals.importAgent.willUpdate');

    await clickButton('modals.importAgent.import');
    const error = document.querySelector(
      '[data-slot="alert"][data-variant="destructive"]',
    );
    expect(error?.getAttribute('role')).toBe('alert');
    expect(error?.textContent).toBe('Import blew up');
    expect(error?.querySelector('svg')?.getAttribute('aria-hidden')).toBe(
      'true',
    );
  });

  it.each([
    [
      {
        success: false,
        error: "This agent is shared with people who can't use it.",
        code: 'team_item_shared_outside',
        message: "This agent is shared with people who can't use it.",
      },
      'settings.teams.errors.teamItemSharedOutside',
    ],
    [
      {
        success: false,
        error: 'team_connection_outside',
        code: 'team_connection_outside',
        message: 'It uses a tool on an account connected for the team.',
      },
      'settings.connectors.team.errors.teamConnectionOutside',
    ],
  ])(
    'words an import over an agent reaching outside its team by its code',
    async (body, key) => {
      service.importAgent.mockResolvedValue({
        ok: false,
        status: 409,
        json: async () => body,
      } as Response);
      act(() => {
        root.render(
          <ImportAgentModal
            modalState="ACTIVE"
            setModalState={() => undefined}
          />,
        );
      });
      const file = new File(['name: Agent\n'], 'agent.yaml', {
        type: 'application/x-yaml',
      });
      await act(async () => dropzone.onDrop!([file], []));
      await flush();
      await clickButton('modals.importAgent.review');
      await clickButton('modals.importAgent.import');
      const error = document.querySelector(
        '[data-slot="alert"][data-variant="destructive"]',
      );
      expect(error?.textContent).toBe(key);
    },
  );

  it('lists folder entries, the plan warnings, and maps a missing folder', async () => {
    service.planImportAgent.mockResolvedValue(
      jsonResponse({
        success: true,
        plan: {
          target: { action: 'create', agent_id: null, matched_by: null },
          sources: [
            {
              name: 'Customs',
              type: 'folder',
              status: 'matched',
              target_id: 'f-9',
            },
            { name: 'Ops', type: 'folder', status: 'missing', target_id: null },
          ],
          tools: [],
          prompt: { status: 'default' },
          models: [],
          warnings: ["Folder 'Ops' not found; left unattached"],
        },
      }),
    );
    act(() => {
      root.render(
        <ImportAgentModal
          modalState="ACTIVE"
          setModalState={() => undefined}
        />,
      );
    });
    const file = new File(['name: Agent\n'], 'agent.yaml', {
      type: 'application/x-yaml',
    });
    await act(async () => dropzone.onDrop!([file], []));
    await flush();
    await clickButton('modals.importAgent.review');

    const warning = document.querySelector(
      '[data-slot="alert"][data-variant="warning"]',
    );
    expect(warning?.textContent).toContain(
      "Folder 'Ops' not found; left unattached",
    );
    const body = document.body.textContent ?? '';
    expect(body).toContain('modals.importAgent.folderMatched');
    expect(body).toContain('modals.importAgent.folderMissing');
    // Left unmapped, the folder goes unattached: no folder resolution.
    await clickButton('modals.importAgent.import');
    expect(service.importAgent.mock.calls[0][0].resolution).toMatchObject({
      sources: {},
      folders: {},
    });
  });
  const pickOption = async (field: string, option: string) => {
    const trigger = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        'button[role="combobox"]',
      ),
    ).find((b) => b.labels?.[0]?.textContent === field);
    expect(trigger).toBeDefined();
    await act(async () => {
      trigger!.dispatchEvent(
        new PointerEvent('pointerdown', {
          bubbles: true,
          button: 0,
          pointerType: 'mouse',
        }),
      );
    });
    const item = Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="option"]'),
    ).find((o) => o.textContent === option);
    expect(item).toBeDefined();
    await act(async () => item!.click());
    await flush();
  };

  const reviewMissing = async () => {
    service.planImportAgent.mockResolvedValue(
      jsonResponse({
        success: true,
        plan: {
          target: { action: 'create', agent_id: null, matched_by: null },
          sources: [
            { name: 'Ops & "Rates"', type: 'folder', status: 'missing' },
            { name: 'Q4 & Q3', type: 'local', status: 'missing' },
          ],
          tools: [],
          prompt: { status: 'default' },
          models: [],
        },
      }),
    );
    act(() => {
      root.render(
        <ImportAgentModal
          modalState="ACTIVE"
          setModalState={() => undefined}
        />,
      );
    });
    const file = new File(['name: Agent\n'], 'agent.yaml', {
      type: 'application/x-yaml',
    });
    await act(async () => dropzone.onDrop!([file], []));
    await flush();
    await clickButton('modals.importAgent.review');
  };

  it('labels each mapping select with the folder or source it stands for, names unescaped', async () => {
    await reviewMissing();
    const labels = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        'button[role="combobox"]',
      ),
    ).map((b) => b.labels?.[0]?.textContent);
    expect(labels).toEqual([
      'modals.importAgent.folderFor:Ops & "Rates"',
      'modals.importAgent.sourceFor:Q4 & Q3',
    ]);
    const body = document.body.textContent ?? '';
    expect(body).toContain('modals.importAgent.folderMissing:Ops & "Rates"');
    expect(body).toContain('modals.importAgent.sourceMissing:Q4 & Q3');
    expect(body).not.toContain('&amp;');
  });

  it('sends a missing folder and source mapped by hand', async () => {
    await reviewMissing();
    await pickOption(
      'modals.importAgent.folderFor:Ops & "Rates"',
      'Carriers › Rate archive',
    );
    await pickOption('modals.importAgent.sourceFor:Q4 & Q3', 'Rate sheets');
    await clickButton('modals.importAgent.import');
    expect(service.importAgent.mock.calls[0][0].resolution).toMatchObject({
      sources: { 'Q4 & Q3': 'd-1' },
      folders: { 'Ops & "Rates"': 'f-2' },
    });
  });

  it('takes a mapping back with Leave unattached', async () => {
    await reviewMissing();
    const folderField = 'modals.importAgent.folderFor:Ops & "Rates"';
    const sourceField = 'modals.importAgent.sourceFor:Q4 & Q3';
    await pickOption(folderField, 'Carriers › Rate archive');
    await pickOption(sourceField, 'Rate sheets');
    await pickOption(folderField, 'modals.importAgent.leaveUnattached');
    await pickOption(sourceField, 'modals.importAgent.leaveUnattached');
    await clickButton('modals.importAgent.import');
    const { resolution } = service.importAgent.mock.calls[0][0];
    expect(resolution.folders).toEqual({});
    expect(resolution.sources).toEqual({});
  });

  describe("a team's custom models", () => {
    const reviewModels = async (models: unknown[]) => {
      service.planImportAgent.mockResolvedValue(
        jsonResponse({
          success: true,
          plan: {
            target: { action: 'create', agent_id: null, matched_by: null },
            sources: [],
            tools: [],
            prompt: { status: 'default' },
            models,
          },
        }),
      );
      act(() => {
        root.render(
          <ImportAgentModal
            modalState="ACTIVE"
            setModalState={() => undefined}
          />,
        );
      });
      const file = new File(['name: Agent\n'], 'agent.yaml', {
        type: 'application/x-yaml',
      });
      await act(async () => dropzone.onDrop!([file], []));
      await flush();
      await clickButton('modals.importAgent.review');
    };

    it.each([
      [
        'custom_model_admin_required',
        'settings.customModels.team.errors.adminRequired',
      ],
      [
        'not_available_to_tokens',
        'settings.customModels.team.errors.notAvailableToTokens',
      ],
    ])('says why a model is left off (%s)', async (reason, key) => {
      await reviewModels([
        {
          display_name: 'Ops Mistral',
          status: 'unavailable',
          requires_secrets: [],
          reason,
        },
      ]);
      const warning = Array.from(
        document.querySelectorAll(
          '[data-slot="alert"][data-variant="warning"]',
        ),
      ).find((a) => a.textContent?.includes('Ops Mistral'));
      expect(warning?.textContent).toContain(
        'modals.importAgent.modelLeftOff:Ops Mistral',
      );
      expect(warning?.textContent).toContain(key);
      expect(
        document.querySelector(
          'input[placeholder="modals.importAgent.apiKeyPlaceholder"]',
        ),
      ).toBeNull();
    });

    it('asks a team Admin for the key of a model it adds to the team, and sends it', async () => {
      await reviewModels([
        {
          display_name: 'Ops Mistral',
          status: 'create',
          requires_secrets: ['api_key'],
        },
      ]);
      const input = document.querySelector<HTMLInputElement>(
        'input[placeholder="modals.importAgent.apiKeyPlaceholder"]',
      );
      expect(input).not.toBeNull();
      await act(async () => {
        Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          'value',
        )!.set!.call(input, 'sk-team');
        input!.dispatchEvent(new Event('input', { bubbles: true }));
      });
      await clickButton('modals.importAgent.import');
      const { resolution } = service.importAgent.mock.calls[0][0];
      expect(resolution.models).toEqual({
        'Ops Mistral': { api_key: 'sk-team' },
      });
    });
  });
});
