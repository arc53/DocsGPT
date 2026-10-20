import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const mockDispatch = vi.fn();
vi.mock('react-redux', () => ({
  useDispatch: () => mockDispatch,
  useSelector: (selector: { name?: string }) =>
    selector.name === 'selectToken' ? 'token' : [],
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
    getAgent: () =>
      ok({
        id: 'a1',
        name: 'Renewal desk',
        agent_type: 'workflow',
        workflow: 'w1',
        allowed_actions: ['view', 'edit', 'publish', 'delete'],
        config: {
          api_write_allowlist: ['t1:write'],
          analytics: {
            enabled: true,
            topics: { mode: 'custom', items: [] },
            tags: [],
            digest: false,
          },
        },
      }),
    getConfig: () =>
      ok({ decision_analytics_enabled: true, analytics_max_tags: 5 }),
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
    expect(details().analytics).toMatchObject({
      topics: { mode: 'custom', items: [] },
    });
    expect(sheet.props!.insights).toMatchObject({
      available: true,
      maxTags: 5,
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

  it('sends no config when the insights are unchanged', async () => {
    await render();
    await save();
    expect(updateAgent).toHaveBeenCalledTimes(1);
    expect(sentConfig()).toBeNull();
  });
});
