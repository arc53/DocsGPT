import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

vi.mock('react-redux', () => ({
  useDispatch: () => vi.fn(),
  useSelector: (selector: { name?: string }) =>
    selector.name === 'selectToken' ? 'token' : [],
}));

const mockT = (key: string) => key;
const mockI18n = { language: 'en' };
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT, i18n: mockI18n }),
  Trans: ({ i18nKey }: { i18nKey: string }) => <>{i18nKey}</>,
}));

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

type Props = Record<string, unknown>;
// Every Access details dialog drawn in the last render: the desktop
// builder's, then the phone stand-in's (from its agent ⋯).
let detailsProps: Props[] = [];
let confirmProps: Props[] = [];
vi.mock('../../modals/AgentDetailsModal', () => ({
  default: (props: Props) => {
    detailsProps.push(props);
    return null;
  },
}));
vi.mock('../../modals/ConfirmationModal', () => ({
  default: (props: Props) => {
    confirmProps.push(props);
    return null;
  },
}));
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

import { agentsListPath } from '../paths';
import WorkflowBuilder from './WorkflowBuilder';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname + location.search}</div>;
}

const jsonResponse = (ok: boolean, body: unknown) => ({
  ok,
  json: () => Promise.resolve(body),
});

describe('WorkflowBuilder Access details', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getAgent.mockReset().mockResolvedValue(
      jsonResponse(true, {
        id: 'a1',
        name: 'Renewal desk',
        agent_type: 'workflow',
        status: 'draft',
        key: 'old-key',
        config: { api_write_allowlist: ['tool:revoked'] },
      }),
    );
    deleteAgent.mockReset();
    detailsProps = [];
    confirmProps = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async (path = '/agents/workflow/edit/a1') => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={[path]}>
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

  // The dialogs one fresh render draws, so none is left over from an earlier one.
  const lastDialogs = () => {
    detailsProps = [];
    act(() => {
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
    return detailsProps;
  };

  // The dialog reopens from the agent it is given: a saved allowlist must be
  // on it, or the next change saves onto the old list and drops this one.
  it.each([
    ['desktop', 0],
    ['phone', 1],
  ])('a saved allowlist reaches the %s dialog it reopens', async (_, index) => {
    await render();
    const dialogs = lastDialogs();
    expect(dialogs).toHaveLength(2);
    const onConfigChange = dialogs[index].onConfigChange as
      ((config: unknown) => void) | undefined;
    expect(onConfigChange).toBeTypeOf('function');
    act(() => onConfigChange!({ api_write_allowlist: ['tool:a'] }));
    for (const props of lastDialogs()) {
      const agent = props.agent as { config?: Record<string, unknown> };
      expect(agent.config?.api_write_allowlist).toEqual(['tool:a']);
    }
  });

  it("a key regenerated from the phone's dialog reaches the builder", async () => {
    await render();
    const onKeyRegenerated = lastDialogs()[1].onKeyRegenerated as
      ((key: string) => void) | undefined;
    expect(onKeyRegenerated).toBeTypeOf('function');
    act(() => onKeyRegenerated!('new-key'));
    for (const props of lastDialogs())
      expect((props.agent as { key?: string }).key).toBe('new-key');
  });

  // The desktop builder's ⋯ offers Access details on a draft; so does the
  // phone's, which draws its dialog only when it can open it.
  it("offers a draft's Access details on the phone too", async () => {
    await render();
    expect(lastDialogs()).toHaveLength(2);
  });

  it("a delete from the phone's ⋯ goes back to the agent's folder", async () => {
    deleteAgent.mockResolvedValue(jsonResponse(true, {}));
    await render('/agents/workflow/edit/a1?folder_id=f1');
    // The phone's confirm comes first: the stand-in renders before the builder.
    const handleSubmit = confirmProps.slice(-2)[0]
      .handleSubmit as () => Promise<unknown>;
    await act(async () => {
      await handleSubmit();
    });
    expect(container.querySelector('[data-testid="where"]')?.textContent).toBe(
      agentsListPath('f1'),
    );
  });
});
