import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
  MemoryRouter,
  Route,
  Routes,
  useNavigate,
  useLocation,
  useParams,
  type NavigateFunction,
} from 'react-router-dom';

// No agent in the store: the guard reads each agent itself.
const state = {
  preference: {
    token: null,
    agents: [] as unknown[],
    sharedAgents: [],
    selectedAgent: null,
  },
};
vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector(state),
}));

// The server's copy of agent `a`; a test renames it between pages.
const server = vi.hoisted(() => ({ name: 'old' }));
const getAgent = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: { getAgent: (...args: unknown[]) => getAgent(...args) },
}));

// Two agent pages that show the agent `useAgent` hands them.
vi.mock('./AgentLogs', async () => {
  const { useAgent } = await import('./hooks/useAgent');
  return {
    default: function AgentLogs() {
      const { agentId } = useParams();
      const { agent } = useAgent(agentId);
      return <div data-testid="logs">{agent?.name}</div>;
    },
  };
});
vi.mock('./AgentInsights', async () => {
  const { useAgent } = await import('./hooks/useAgent');
  return {
    default: function AgentInsights() {
      const { agentId } = useParams();
      const { agent } = useAgent(agentId);
      return <div data-testid="insights">{agent?.name}</div>;
    },
  };
});
vi.mock('./AgentAnalytics', () => ({ default: () => null }));
vi.mock('./AgentsList', () => ({ default: () => null }));
vi.mock('./NewAgent', () => ({
  default: () => <input data-testid="classic-form" name="name" />,
}));
vi.mock('./schedules/SchedulesView', () => ({ default: () => null }));
vi.mock('./SharedAgent', () => ({ default: () => null }));
vi.mock('./workflow/WorkflowBuilder', () => ({
  default: () => <div data-testid="workflow-builder" />,
}));

import Agents from './index';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Agents routes and the route guard', () => {
  let container: HTMLDivElement;
  let root: Root;
  let navigate: NavigateFunction;

  function CaptureNavigate() {
    navigate = useNavigate();
    return null;
  }

  beforeEach(() => {
    server.name = 'old';
    getAgent.mockReset();
    getAgent.mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            id: 'a',
            name: server.name,
            allowed_actions: ['view', 'view_logs'],
          }),
      }),
    );
    container = document.createElement('div');
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
  });

  // Without the app's boundary keyed by path: the guard alone must not
  // carry one page's read of the agent to another page.
  it("reads the agent again on another of its pages, not the last page's copy", async () => {
    await act(async () =>
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/logs/a']}>
          <Routes>
            <Route path="/agents/*" element={<Agents />} />
          </Routes>
          <CaptureNavigate />
        </MemoryRouter>,
      ),
    );
    await act(async () => undefined);
    expect(container.textContent).toBe('old');

    server.name = 'new';
    await act(async () => navigate('/agents/manage/insights/a'));
    await act(async () => undefined);
    expect(container.querySelector('[data-testid="insights"]')).not.toBeNull();
    expect(container.textContent).toBe('new');
  });

  // The Teams fallback, an old `/agents/edit/<id>` bookmark or a typed URL
  // reach a workflow on the classic edit path, whose form would save it
  // back as a classic agent.
  it('opens a workflow agent on the classic edit path in the workflow editor', async () => {
    getAgent.mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            id: 'a',
            name: 'flow',
            agent_type: 'workflow',
            allowed_actions: ['view'],
          }),
      }),
    );
    let pathname = '';
    function CapturePath() {
      pathname = useLocation().pathname;
      return null;
    }
    await act(async () =>
      root.render(
        <MemoryRouter initialEntries={['/agents/edit/a']}>
          <Routes>
            <Route path="/agents/*" element={<Agents />} />
          </Routes>
          <CapturePath />
        </MemoryRouter>,
      ),
    );
    await act(async () => undefined);
    await act(async () => undefined);
    expect(pathname).toBe('/agents/manage/workflow/edit/a');
    expect(
      container.querySelector('[data-testid="workflow-builder"]'),
    ).not.toBeNull();
    expect(container.querySelector('[data-testid="classic-form"]')).toBeNull();
  });

  it('keeps a classic agent on the classic edit path', async () => {
    await act(async () =>
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/edit/a']}>
          <Routes>
            <Route path="/agents/*" element={<Agents />} />
          </Routes>
        </MemoryRouter>,
      ),
    );
    await act(async () => undefined);
    expect(
      container.querySelector('[data-testid="classic-form"]'),
    ).not.toBeNull();
  });
});
