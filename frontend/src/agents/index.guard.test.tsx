import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
  MemoryRouter,
  Route,
  Routes,
  useNavigate,
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
vi.mock('./NewAgent', () => ({ default: () => null }));
vi.mock('./schedules/SchedulesView', () => ({ default: () => null }));
vi.mock('./SharedAgent', () => ({ default: () => null }));
vi.mock('./workflow/WorkflowBuilder', () => ({ default: () => null }));

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
});
