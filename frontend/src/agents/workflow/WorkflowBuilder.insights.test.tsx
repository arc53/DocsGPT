import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const mockDispatch = vi.fn();
vi.mock('react-redux', () => ({
  useDispatch: () => mockDispatch,
  useSelector: (selector: { name?: string }) =>
    ({
      selectToken: 'token',
      // The server's switch and limits, as /api/config left them.
      selectAnalyticsEnabled: true,
      selectAnalyticsMaxTopics: 15,
      selectAnalyticsMaxOverlapping: 5,
    })[selector.name ?? ''] ?? [],
}));

const mockT = (key: string) => key;
const mockI18n = { language: 'en' };
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT, i18n: mockI18n }),
  Trans: ({ i18nKey }: { i18nKey: string }) => <>{i18nKey}</>,
}));

// The canvas itself is out of scope: a plain stand-in for reactflow.
vi.mock('reactflow', () => {
  const noop = () => undefined;
  const flow = {
    fitView: noop,
    getViewport: () => ({ x: 0, y: 0, zoom: 1 }),
    screenToFlowPosition: (p: unknown) => p,
    project: (p: unknown) => p,
    setCenter: noop,
    zoomIn: noop,
    zoomOut: noop,
    getNodes: () => [],
    getEdges: () => [],
  };
  return {
    default: () => <div data-testid="canvas" />,
    ReactFlowProvider: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    Background: () => null,
    useReactFlow: () => flow,
    addEdge: (_e: unknown, edges: unknown) => edges,
    applyEdgeChanges: (_c: unknown, edges: unknown) => edges,
    applyNodeChanges: (_c: unknown, nodes: unknown) => nodes,
  };
});
vi.mock('reactflow/dist/style.css', () => ({}));

// The delete confirm's props; the test calls its handleSubmit directly.
const confirmProps: { current: Record<string, unknown> | null } = {
  current: null,
};
vi.mock('../../modals/ConfirmationModal', () => ({
  default: (props: Record<string, unknown>) => {
    confirmProps.current = props;
    return null;
  },
}));
vi.mock('../../modals/AgentDetailsModal', () => ({ default: () => null }));
vi.mock('../../teams/ShareToTeamModal', () => ({ default: () => null }));
vi.mock('../components/AgentPreviewSheet', () => ({ default: () => null }));
vi.mock('./WorkflowPreview', () => ({ default: () => null }));
vi.mock('./NodePalette', () => ({ default: () => null }));
vi.mock('./CanvasControls', () => ({ default: () => null }));

const updateAgent = vi.fn();
const updateWorkflow = vi.fn();
const getAgent = vi.fn();
const AGENT = {
  id: 'a1',
  name: 'Renewal desk',
  agent_type: 'workflow',
  workflow: 'w1',
  allowed_actions: ['view', 'edit', 'publish', 'delete'],
  config: {
    api_write_allowlist: ['t1:write'],
    analytics: {
      enabled: true,
      topics: [],
      hidden_folders: [],
      digest: false,
    },
  },
};
const WORKFLOW = {
  workflow: { name: 'Renewal desk', description: '' },
  nodes: [
    { id: 'start', type: 'start', title: 'Start', position: { x: 0, y: 0 } },
    {
      id: 'agent',
      type: 'agent',
      title: 'Agent',
      position: { x: 0, y: 100 },
      data: { model_id: 'm1', llm_name: 'openai', prompt_template: 'Hi' },
    },
    { id: 'end', type: 'end', title: 'End', position: { x: 0, y: 200 } },
  ],
  edges: [
    { id: 'e1', source: 'start', target: 'agent' },
    { id: 'e2', source: 'agent', target: 'end' },
  ],
};
const ok = (body: unknown) =>
  Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
vi.mock('../../api/services/userService', () => ({
  default: {
    getAgent: (...a: unknown[]) => getAgent(...a),
    updateAgent: (...a: unknown[]) => updateAgent(...a),
    updateWorkflow: (...a: unknown[]) => updateWorkflow(...a),
    getUserTools: () => ok({ tools: [] }),
    getWorkflow: () => ok({ success: true, data: WORKFLOW }),
  },
}));
const sheet = vi.hoisted(() => ({
  props: null as Record<string, unknown> | null,
}));
vi.mock('./components/WorkflowDetailsSheet', () => ({
  default: (props: Record<string, unknown>) => {
    sheet.props = props;
    return null;
  },
}));
vi.mock('../../api/services/modelService', () => ({
  default: {
    getModels: () =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    transformModels: () => [],
  },
}));

import WorkflowBuilder from './WorkflowBuilder';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// IN-21: a workflow's insights are edited in Workflow details and saved with
// the workflow, as `config` with only `analytics` replaced.
describe('WorkflowBuilder insights', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    updateAgent.mockReset().mockImplementation(() => ok({ id: 'a1' }));
    updateWorkflow.mockReset().mockImplementation(() => ok({ success: true }));
    getAgent.mockReset().mockImplementation(() => ok(AGENT));
    sheet.props = null;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/workflow/edit/a1']}>
          <Routes>
            <Route
              path="/agents/workflow/edit/:agentId"
              element={<WorkflowBuilder />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    await act(async () => undefined);
  };

  const details = () =>
    sheet.props!.details as { analytics?: Record<string, unknown> };
  const save = async (analytics?: Record<string, unknown>) => {
    const onSave = sheet.props!.onSave as (values: object) => void;
    await act(async () =>
      onSave({
        name: 'Renewal desk',
        description: '',
        allowPromptOverride: false,
        imageFile: null,
        analytics: analytics ?? details().analytics,
      }),
    );
    await act(async () => undefined);
  };
  const sentConfig = () => {
    const form = updateAgent.mock.calls.at(-1)![1] as FormData;
    const raw = form.get('config');
    return raw === null ? null : JSON.parse(raw as string);
  };

  it('hands the details panel the saved insights, the server switch and the limits', async () => {
    await render();
    expect(details().analytics).toMatchObject({ topics: [] });
    expect(sheet.props!.insights).toMatchObject({
      available: true,
      maxOverlapping: 5,
      agentId: 'a1',
      token: 'token',
    });
  });

  it('sends config with only analytics replaced when the insights changed', async () => {
    await render();
    const next = { ...details().analytics, digest: true };
    await save(next);
    expect(updateAgent).toHaveBeenCalledTimes(1);
    expect(sentConfig()).toEqual({
      api_write_allowlist: ['t1:write'],
      analytics: next,
    });
    // The saved copy moves on: the next save starts from it.
    expect(details().analytics).toEqual(next);
    await save();
    expect(updateAgent).toHaveBeenCalledTimes(2);
    expect(sentConfig()).toBeNull();
  });

  it('sends the context limit over the saved config, and only when it changed', async () => {
    await render();
    const saveLimit = async (contextWindowLimit: number | null) => {
      const onSave = sheet.props!.onSave as (values: object) => void;
      await act(async () =>
        onSave({
          name: 'Renewal desk',
          description: '',
          allowPromptOverride: false,
          imageFile: null,
          analytics: details().analytics,
          contextWindowLimit,
        }),
      );
      await act(async () => undefined);
    };
    await saveLimit(32000);
    expect(sentConfig()).toEqual({
      ...AGENT.config,
      context_window_limit: 32000,
    });
    expect(
      (sheet.props!.details as { contextWindowLimit: number | null })
        .contextWindowLimit,
    ).toBe(32000);
    await saveLimit(32000);
    expect(sentConfig()).toBeNull();
    await saveLimit(null);
    expect(sentConfig()).toMatchObject({ context_window_limit: null });
  });

  it('sends the history limit over the saved config, and only when it changed', async () => {
    await render();
    const saveLimit = async (historyTokenLimit: number | null) => {
      const onSave = sheet.props!.onSave as (values: object) => void;
      await act(async () =>
        onSave({
          name: 'Renewal desk',
          description: '',
          allowPromptOverride: false,
          imageFile: null,
          analytics: details().analytics,
          contextWindowLimit: null,
          historyTokenLimit,
        }),
      );
      await act(async () => undefined);
    };
    await saveLimit(8000);
    expect(sentConfig()).toEqual({
      ...AGENT.config,
      history_token_limit: 8000,
    });
    await saveLimit(8000);
    expect(sentConfig()).toBeNull();
  });

  it('sends no config when the insights are unchanged', async () => {
    await render();
    await save();
    expect(updateAgent).toHaveBeenCalledTimes(1);
    expect(sentConfig()).toBeNull();
  });

  it('keeps toolbar Save on for an insights edit left by a failed save', async () => {
    await render();
    updateAgent
      .mockReset()
      .mockImplementation(() =>
        Promise.resolve({ ok: false, json: () => Promise.resolve({}) }),
      );
    await save({ ...details().analytics, digest: true });
    const onOpenChange = sheet.props!.onOpenChange as (open: boolean) => void;
    await act(async () => onOpenChange(false));
    const saveButton = [...container.querySelectorAll('button')].find(
      (button) => button.textContent === 'agents.form.buttons.save',
    );
    expect(container.textContent).toContain(
      'agents.workflow.builder.unsavedChanges',
    );
    expect(saveButton?.disabled).toBe(false);
  });
  // Saved elsewhere since the builder loaded (another tab, another editor):
  // an insights save must not put the old guardrails or allowlist back.
  it('puts the new insights on the config as the server has it at save time', async () => {
    await render();
    const fresh = {
      ...AGENT.config,
      api_write_allowlist: [],
      guardrails: { enabled: true, controls: [{ id: 'pii' }] },
    };
    getAgent.mockImplementation(() => ok({ ...AGENT, config: fresh }));
    const next = { ...details().analytics, digest: true };
    await save(next);
    expect(updateAgent).toHaveBeenCalledTimes(1);
    expect(sentConfig()).toEqual({ ...fresh, analytics: next });
  });

  it('fails the save when the fresh read fails, keeping the edit', async () => {
    await render();
    getAgent.mockImplementation(() =>
      Promise.resolve({ ok: false, json: () => Promise.resolve({}) }),
    );
    const onOpenChange = sheet.props!.onOpenChange as (o: boolean) => void;
    await act(async () => onOpenChange(true));
    const next = { ...details().analytics, digest: true };
    await save(next);
    expect(updateAgent).not.toHaveBeenCalled();
    expect(sheet.props!.open).toBe(true);
    expect((sheet.props!.errors as string[]).length).toBeGreaterThan(0);
    expect(details().analytics).toEqual(next);
  });

  describe('while a details save is out', () => {
    let finish: (value: unknown) => void;
    const openDetails = async () => {
      const onOpenChange = sheet.props!.onOpenChange as (o: boolean) => void;
      await act(async () => onOpenChange(true));
    };

    beforeEach(() => {
      updateAgent.mockReset().mockReturnValue(
        new Promise((resolve) => {
          finish = resolve;
        }),
      );
    });

    it('keeps the panel open until the save answers, then closes it', async () => {
      await render();
      await openDetails();
      await save({ ...details().analytics, digest: true });
      expect(sheet.props!.saving).toBe(true);
      const onOpenChange = sheet.props!.onOpenChange as (o: boolean) => void;
      await act(async () => onOpenChange(false));
      expect(sheet.props!.open).toBe(true);
      await act(async () =>
        finish({ ok: true, json: () => Promise.resolve({ id: 'a1' }) }),
      );
      await act(async () => undefined);
      expect(sheet.props!.open).toBe(false);
    });

    it('starts no second save beside it', async () => {
      await render();
      await openDetails();
      await save({ ...details().analytics, digest: true });
      await save({ ...details().analytics, digest: true });
      expect(updateWorkflow).toHaveBeenCalledTimes(1);
      await act(async () =>
        finish({ ok: true, json: () => Promise.resolve({ id: 'a1' }) }),
      );
      await act(async () => undefined);
      expect(updateWorkflow).toHaveBeenCalledTimes(1);
    });
  });
});
