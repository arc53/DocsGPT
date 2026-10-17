import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

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

const getAgent = vi.fn();
const deleteAgent = vi.fn();
vi.mock('../../api/services/userService', () => ({
  default: {
    getAgent: (...a: unknown[]) => getAgent(...a),
    deleteAgent: (...a: unknown[]) => deleteAgent(...a),
    getUserTools: () =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ tools: [] }) }),
    getWorkflow: () => Promise.resolve({ ok: false, json: () => ({}) }),
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

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

const jsonResponse = (ok: boolean, body: unknown) => ({
  ok,
  json: () => Promise.resolve(body),
});

describe('WorkflowBuilder delete', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getAgent.mockReset().mockResolvedValue(
      jsonResponse(true, {
        id: 'a1',
        name: 'Renewal desk',
        agent_type: 'workflow',
      }),
    );
    deleteAgent.mockReset();
    confirmProps.current = null;
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
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>,
      );
    });
  };

  const submit = async () => {
    const handleSubmit = confirmProps.current!.handleSubmit as () => unknown;
    let result: unknown;
    await act(async () => {
      result = handleSubmit();
      await (result as Promise<unknown>).catch(() => undefined);
    });
    return result as Promise<unknown>;
  };

  it('a failed delete rejects with the server message in the confirm, not the canvas', async () => {
    deleteAgent.mockResolvedValue(
      jsonResponse(false, { message: 'Agent is in use.' }),
    );
    await render();
    await expect(submit()).rejects.toThrow('Agent is in use.');
    expect(deleteAgent).toHaveBeenCalledWith('a1', 'token');
    expect(confirmProps.current?.error).toBe('Agent is in use.');
    // No floating publish-error Alert on the canvas.
    expect(container.querySelector('[data-slot="alert"]')).toBeNull();
    expect(container.querySelector('[data-testid="where"]')).toBeNull();
  });

  it('falls back to deleteFailed when the server sends no message', async () => {
    deleteAgent.mockResolvedValue(jsonResponse(false, {}));
    await render();
    await expect(submit()).rejects.toThrow();
    expect(confirmProps.current?.error).toBe(
      'agents.workflow.builder.deleteFailed',
    );
  });

  it('a successful delete resolves and goes back to the agents list', async () => {
    deleteAgent.mockResolvedValue(jsonResponse(true, {}));
    await render();
    await expect(submit()).resolves.toBeUndefined();
    expect(container.querySelector('[data-testid="where"]')).not.toBeNull();
  });
});
