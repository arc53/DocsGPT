import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const state = {
  preference: {
    token: null,
    agents: [] as unknown[],
    sharedAgents: [],
    selectedAgent: null,
  },
};

const mocks = vi.hoisted(() => ({ getAgent: vi.fn() }));

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector(state),
}));

vi.mock('../api/services/userService', () => ({
  default: { getAgent: mocks.getAgent },
}));

import AgentRouteGuard from './AgentRouteGuard';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const respond = (body: unknown, ok = true) =>
  Promise.resolve({ ok, json: () => Promise.resolve(body) });

describe('AgentRouteGuard', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    state.preference.agents = [];
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    mocks.getAgent.mockReset();
  });

  const render = async (action: string, path = '/agents/manage/logs/a1') => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route
              path="/agents/manage/:page/:agentId"
              element={
                <AgentRouteGuard action={action}>
                  <div data-testid="page" />
                </AgentRouteGuard>
              }
            />
            <Route path="/agents/manage" element={<div data-testid="list" />} />
          </Routes>
        </MemoryRouter>,
      );
    });
  };

  const shows = (id: string) =>
    container.querySelector(`[data-testid="${id}"]`) !== null;

  it('sends a viewer back to the list without showing the page', async () => {
    let resolve: (v: unknown) => void = () => undefined;
    mocks.getAgent.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    await render('view', '/agents/manage/edit/a1');
    // Nothing of the page while the agent loads, only the loading ring.
    expect(shows('page')).toBe(false);
    const loading = container.querySelector('[data-slot="loading-state"]');
    expect(loading?.getAttribute('data-fill')).toBe('parent');
    expect(loading?.querySelector('[role="status"]')).not.toBeNull();
    await act(async () =>
      resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            id: 'a1',
            access: 'viewer',
            allowed_actions: ['pin', 'use'],
          }),
      }),
    );
    expect(shows('page')).toBe(false);
    expect(shows('list')).toBe(true);
    // The redirect itself is silent.
    expect(container.querySelector('[data-slot="loading-state"]')).toBeNull();
  });

  it('lets an editor open the page', async () => {
    mocks.getAgent.mockReturnValue(
      respond({
        id: 'a1',
        access: 'editor',
        allowed_actions: ['view', 'view_logs'],
      }),
    );
    await render('view_logs');
    expect(shows('page')).toBe(true);
  });

  it('decides from the agent list without a fetch when it has the actions', async () => {
    state.preference.agents = [
      { id: 'a1', access: 'viewer', allowed_actions: ['pin', 'use'] },
    ];
    await render('manage_schedules', '/agents/manage/schedules/a1');
    expect(mocks.getAgent).not.toHaveBeenCalled();
    expect(shows('list')).toBe(true);
  });

  it('sends the caller back when the agent does not load', async () => {
    mocks.getAgent.mockReturnValue(respond({}, false));
    await render('view_logs');
    expect(shows('list')).toBe(true);
  });

  it('lets an owner in when the record has no access fields', async () => {
    mocks.getAgent.mockReturnValue(respond({ id: 'a1' }));
    await render('view');
    expect(shows('page')).toBe(true);
  });
});
