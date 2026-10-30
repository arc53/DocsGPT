import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
  MemoryRouter,
  Route,
  Routes,
  useNavigate,
  useParams,
  type NavigateFunction,
} from 'react-router-dom';

// Counts mounts, and shows the agent it was mounted for next to the
// route's current one.
const mounts = vi.hoisted(() => ({ count: 0 }));
vi.mock('./workflow/WorkflowBuilder', () => ({
  default: function WorkflowBuilder() {
    const { agentId } = useParams();
    const [mountedFor] = useState(() => {
      mounts.count += 1;
      return agentId;
    });
    return (
      <div data-testid="builder">
        {mountedFor}:{agentId}
      </div>
    );
  },
}));
vi.mock('./AgentRouteGuard', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('./AgentLogs', () => ({ default: () => null }));
vi.mock('./AgentsList', () => ({ default: () => null }));
vi.mock('./NewAgent', () => ({ default: () => null }));
vi.mock('./schedules/SchedulesView', () => ({ default: () => null }));
vi.mock('./SharedAgent', () => ({ default: () => null }));

import Agents from './index';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Agents routes', () => {
  let container: HTMLDivElement;
  let root: Root;
  let navigate: NavigateFunction;

  function CaptureNavigate() {
    navigate = useNavigate();
    return null;
  }

  beforeEach(() => {
    mounts.count = 0;
    container = document.createElement('div');
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
  });

  // The builder holds one workflow's state; another workflow's edit page
  // must not inherit it.
  it("opens another workflow's edit page in a fresh builder", async () => {
    await act(async () =>
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/workflow/edit/a']}>
          <Routes>
            <Route path="/agents/*" element={<Agents />} />
          </Routes>
          <CaptureNavigate />
        </MemoryRouter>,
      ),
    );
    expect(container.textContent).toBe('a:a');

    await act(async () => navigate('/agents/manage/workflow/edit/b'));
    expect(container.textContent).toBe('b:b');
    expect(mounts.count).toBe(2);
  });
});
