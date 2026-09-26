import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({ preference: { token: 'token', sourceDocs: [] } }),
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
});
