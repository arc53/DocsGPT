import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

// Toasts and labels read as their keys.
vi.mock('i18next', () => ({
  default: { t: (key: string) => key, language: 'en' },
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const userService = vi.hoisted(() => ({
  getSharedAgent: vi.fn(),
  getAgent: vi.fn(),
}));
vi.mock('../api/services/userService', () => ({ default: userService }));
// The page's heavy children: the test is about what it asks for, and when.
vi.mock('../components/MessageInput', () => ({ default: () => null }));
vi.mock('./ConversationMessages', () => ({ default: () => null }));
vi.mock('../components/ArtifactPanel', () => ({ default: () => null }));
vi.mock('./ArtifactsPanel', () => ({ default: () => null }));
vi.mock('../agents/SharedAgentCard', () => ({ default: () => null }));

import AgentRouteGuard from '../agents/AgentRouteGuard';
import SharedAgent from '../agents/SharedAgent';
import actionToastReducer from '../notifications/actionToastSlice';
import { prefSlice } from '../preferences/preferenceSlice';
import uploadReducer from '../upload/uploadSlice';
import {
  requestWorkspace,
  setRequestWorkspace,
} from '../workspace/requestWorkspace';
import { workspaceListenerMiddleware } from '../workspace/workspaceListener';
import workspaceReducer, {
  loadWorkspaces,
  switchWorkspace,
} from '../workspace/workspaceSlice';
import { conversationSlice } from './conversationSlice';
import { followItemWorkspace, followStep } from './followWorkspace';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const ROWS = [
  { id: 'personal', kind: 'personal', name: 'Personal' },
  { id: 't1', kind: 'team', name: 'Operations', role: 'viewer' },
];

const listLoaded = () => ({
  type: loadWorkspaces.fulfilled.type,
  payload: ROWS,
  meta: { requestId: null, arg: { token: null } },
});

const makeStore = (current = 'personal', loaded = true) => {
  const store = configureStore({
    reducer: {
      workspace: workspaceReducer,
      actionToast: actionToastReducer,
      preference: prefSlice.reducer,
      conversation: conversationSlice.reducer,
      upload: uploadReducer,
    },
    middleware: (getDefault) =>
      getDefault({ serializableCheck: false }).prepend(
        workspaceListenerMiddleware.middleware,
      ),
  });
  if (loaded) store.dispatch(listLoaded());
  if (current !== 'personal') store.dispatch(switchWorkspace(current));
  return store;
};

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => {
  setRequestWorkspace('personal', 0);
  localStorage.clear();
});

describe('followStep', () => {
  const state = (current: string, loaded = true) =>
    makeStore(current, loaded).getState().workspace;

  it('nothing for an item already in the current workspace', () => {
    expect(followStep({ kind: 'team', team_id: 't1' }, state('t1')).kind).toBe(
      'none',
    );
    expect(followStep({ kind: 'personal' }, state('personal')).kind).toBe(
      'none',
    );
    expect(followStep(undefined, state('personal')).kind).toBe('none');
  });

  it('a team the caller is in, and Personal, are followed', () => {
    expect(
      followStep({ kind: 'team', team_id: 't1' }, state('personal')),
    ).toEqual({ kind: 'switch', target: 't1', name: 'Operations' });
    expect(followStep({ kind: 'personal' }, state('t1'))).toEqual({
      kind: 'switch',
      target: 'personal',
      name: 'workspace.switcher.personal',
    });
  });

  it("a team the caller isn't in is left alone", () => {
    expect(
      followStep({ kind: 'team', team_id: 't9' }, state('personal')).kind,
    ).toBe('none');
  });

  it('waits for the workspace list before following a team', () => {
    expect(
      followStep({ kind: 'team', team_id: 't1' }, state('personal', false))
        .kind,
    ).toBe('wait');
  });
});

describe('followItemWorkspace: a chat opened by its link', () => {
  it('loading a team chat switches to its team and says so', async () => {
    const store = makeStore('personal');
    const switched = await store.dispatch(
      followItemWorkspace({ kind: 'team', team_id: 't1' }),
    );
    expect(switched).toBe(true);
    expect(store.getState().workspace.current).toBe('t1');
    expect(store.getState().workspace.lastReason).toBe('link');
    // Requests go to the team before the chat applies.
    expect(requestWorkspace()).toBe('t1');
    expect(store.getState().actionToast.current?.message).toBe(
      'workspace.notices.switched',
    );
  });

  it('a chat in the current workspace stays put', async () => {
    const store = makeStore('t1');
    const epoch = store.getState().workspace.epoch;
    await expect(
      store.dispatch(followItemWorkspace({ kind: 'team', team_id: 't1' })),
    ).resolves.toBe(false);
    expect(store.getState().workspace.epoch).toBe(epoch);
  });

  it('waits for the list, then follows', async () => {
    const store = makeStore('personal', false);
    const follow = store.dispatch(
      followItemWorkspace({ kind: 'team', team_id: 't1' }),
    );
    await flush();
    expect(store.getState().workspace.current).toBe('personal');
    store.dispatch(listLoaded());
    await expect(follow).resolves.toBe(true);
    expect(store.getState().workspace.current).toBe('t1');
  });

  it('gives up waiting when the list never comes', async () => {
    vi.useFakeTimers();
    try {
      const store = makeStore('personal', false);
      const follow = store.dispatch(
        followItemWorkspace(
          { kind: 'team', team_id: 't1' },
          { timeoutMs: 100 },
        ),
      );
      await vi.advanceTimersByTimeAsync(150);
      await expect(follow).resolves.toBe(false);
      expect(store.getState().workspace.current).toBe('personal');
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('a shared agent opened from inside a team', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    root = createRoot(container);
    userService.getSharedAgent.mockReset();
  });

  afterEach(() => {
    act(() => root.unmount());
  });

  it('switches to Personal before asking for the agent or the chat', async () => {
    const store = makeStore('t1');
    const askedIn: string[] = [];
    userService.getSharedAgent.mockImplementation(async () => {
      askedIn.push(requestWorkspace());
      return new Response(
        JSON.stringify({ id: 'a1', name: 'Helper', starters: [] }),
        { status: 200 },
      );
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={['/agents/shared/tok-1']}>
            <Routes>
              <Route path="/agents/shared/:agentId" element={<SharedAgent />} />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
    await act(flush);
    expect(store.getState().workspace.current).toBe('personal');
    expect(askedIn.length).toBeGreaterThan(0);
    expect(askedIn.every((workspace) => workspace === 'personal')).toBe(true);
    expect(store.getState().preference.selectedAgent?.id).toBe('a1');
  });

  it('asks at once in Personal', async () => {
    const store = makeStore('personal');
    userService.getSharedAgent.mockResolvedValue(
      new Response(JSON.stringify({ id: 'a1', name: 'Helper' }), {
        status: 200,
      }),
    );
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={['/agents/shared/tok-1']}>
            <Routes>
              <Route path="/agents/shared/:agentId" element={<SharedAgent />} />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
    await act(flush);
    expect(userService.getSharedAgent).toHaveBeenCalledTimes(1);
    expect(store.getState().workspace.epoch).toBe(0);
  });
});

describe("a team agent's page opened by its link from Personal", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    root = createRoot(container);
    userService.getAgent.mockReset();
  });

  afterEach(() => {
    act(() => root.unmount());
  });

  it("switches to the agent's team without drawing the page first", async () => {
    const store = makeStore('personal');
    userService.getAgent.mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 'a1',
          name: 'Carrier desk',
          allowed_actions: ['view_logs'],
          workspace: { kind: 'team', team_id: 't1' },
        }),
        { status: 200 },
      ),
    );
    const drawn: string[] = [];
    function Page() {
      drawn.push(requestWorkspace());
      return null;
    }
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={['/agents/manage/logs/a1']}>
            <Routes>
              <Route
                path="/agents/manage/logs/:agentId"
                element={
                  <AgentRouteGuard action="view_logs">
                    <Page />
                  </AgentRouteGuard>
                }
              />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
    await act(flush);
    expect(store.getState().workspace.current).toBe('t1');
    expect(store.getState().workspace.lastReason).toBe('link');
    // Without the page area's remount the page shows only once in the team.
    expect(drawn.every((workspace) => workspace === 't1')).toBe(true);
  });
});
