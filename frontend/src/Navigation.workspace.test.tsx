import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

const userService = vi.hoisted(() => ({
  getPinnedAgents: vi.fn(),
  getAgents: vi.fn(),
}));
vi.mock('./api/services/userService', () => ({ default: userService }));
const prefApi = vi.hoisted(() => ({ getConversations: vi.fn() }));
vi.mock('./preferences/preferenceApi', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getConversations: prefApi.getConversations,
}));
const client = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('./api/client', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  default: client,
}));

import { MemoryRouter } from 'react-router-dom';

import type { Agent } from './agents/types';
import SidebarTeamEntry from './navigation/SidebarTeamEntry';
import useRecentAgents from './navigation/useRecentAgents';
import {
  deleteAllChats,
  deleteAllChatsCopy,
  loadOlderChats,
  refreshChats,
} from './navigation/sidebarChats';
import { prefSlice } from './preferences/preferenceSlice';
import {
  requestWorkspace,
  setRequestWorkspace,
  WORKSPACE_HEADER,
} from './workspace/requestWorkspace';
import { workspaceListenerMiddleware } from './workspace/workspaceListener';
import workspaceReducer, {
  loadWorkspaces,
  switchWorkspace,
} from './workspace/workspaceSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const ROWS = [
  { id: 'personal', kind: 'personal', name: 'Personal' },
  { id: 't1', kind: 'team', name: 'Operations', role: 'editor' },
];

const makeStore = (current = 'personal') => {
  const store = configureStore({
    reducer: { workspace: workspaceReducer, preference: prefSlice.reducer },
    middleware: (getDefault) =>
      getDefault({ serializableCheck: false }).prepend(
        workspaceListenerMiddleware.middleware,
      ),
  });
  store.dispatch({
    type: loadWorkspaces.fulfilled.type,
    payload: ROWS,
    meta: { requestId: null, arg: { token: null } },
  });
  if (current !== 'personal') store.dispatch(switchWorkspace(current));
  return store;
};

const ok = (body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));

/** A request the test answers when it chooses. */
function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const agent = (id: string, pinned = false): Agent =>
  ({
    id,
    name: id,
    status: 'published',
    pinned,
  }) as Agent;

beforeEach(() => {
  userService.getPinnedAgents.mockReset();
  userService.getAgents.mockReset();
  prefApi.getConversations.mockReset();
  client.get.mockReset();
});

afterEach(() => {
  setRequestWorkspace('personal', 0);
  localStorage.clear();
});

describe('sidebar pins and recent agents', () => {
  let container: HTMLDivElement;
  let root: Root;
  let shown: Agent[] = [];

  function Pins() {
    shown = useRecentAgents();
    return null;
  }

  beforeEach(() => {
    container = document.createElement('div');
    root = createRoot(container);
    shown = [];
  });

  afterEach(() => act(() => root.unmount()));

  it('load again for the workspace switched to, and drop the old ones', async () => {
    const store = makeStore('personal');
    const asked: string[] = [];
    userService.getPinnedAgents.mockImplementation(() => {
      asked.push(requestWorkspace());
      return requestWorkspace() === 't1'
        ? ok([
            agent('team-a', true),
            agent('team-b', true),
            agent('team-c', true),
          ])
        : ok([
            agent('mine', true),
            agent('mine-2', true),
            agent('mine-3', true),
          ]);
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <Pins />
        </Provider>,
      );
    });
    await act(flush);
    expect(shown.map((a) => a.id)).toEqual(['mine', 'mine-2', 'mine-3']);

    await act(async () => {
      store.dispatch(switchWorkspace('t1'));
    });
    await act(flush);
    expect(asked).toContain('t1');
    expect(shown.map((a) => a.id)).toEqual(['team-a', 'team-b', 'team-c']);
  });

  it("an answer for the old workspace doesn't land in the new one", async () => {
    const store = makeStore('personal');
    const slow = deferred<Response>();
    userService.getPinnedAgents
      .mockImplementationOnce(() => slow.promise)
      .mockImplementation(() =>
        ok([agent('team-a', true), agent('b', true), agent('c', true)]),
      );
    await act(async () => {
      root.render(
        <Provider store={store}>
          <Pins />
        </Provider>,
      );
    });
    await act(async () => {
      store.dispatch(switchWorkspace('t1'));
    });
    await act(flush);
    await act(async () => {
      slow.resolve(
        new Response(
          JSON.stringify([
            agent('mine', true),
            agent('x', true),
            agent('y', true),
          ]),
        ),
      );
    });
    await act(flush);
    expect(shown.map((a) => a.id)).toEqual(['team-a', 'b', 'c']);
  });
});

describe('sidebar chats', () => {
  it('a refresh sent before a switch is dropped', async () => {
    const store = makeStore('personal');
    const slow = deferred<unknown>();
    prefApi.getConversations.mockReturnValueOnce(slow.promise);
    const refresh = store.dispatch(refreshChats(null));
    store.dispatch(switchWorkspace('t1'));
    slow.resolve({ data: [{ id: 'old', name: 'Old chat' }], loading: false });
    await refresh;
    expect(store.getState().preference.conversations.data).toBeNull();
  });

  it('older chats from before a switch are dropped', async () => {
    const store = makeStore('personal');
    const slow = deferred<unknown>();
    prefApi.getConversations.mockReturnValueOnce(slow.promise);
    const older = store.dispatch(
      loadOlderChats(null, { date: '2026-01-01', id: 'c1' }),
    );
    store.dispatch(switchWorkspace('t1'));
    slow.resolve({ data: [{ id: 'old', name: 'Old chat' }], loading: false });
    await expect(older).resolves.toBe('stale');
    expect(store.getState().preference.conversations.data).toBeNull();
  });
});

describe('delete all chats', () => {
  const t = ((key: string, opts?: { name?: string }) =>
    opts?.name ? `${key}(${opts.name})` : key) as never;

  it('names the workspace it clears', () => {
    expect(
      deleteAllChatsCopy(t, { id: 't1', kind: 'team', name: 'Operations' }),
    ).toEqual({
      message: 'workspace.chat.deleteAll.confirm(Operations)',
      description: 'workspace.chat.deleteAll.consequence(Operations)',
    });
    expect(
      deleteAllChatsCopy(t, { id: 'personal', kind: 'personal', name: 'P' })
        .message,
    ).toBe('workspace.chat.deleteAll.confirm(workspace.switcher.personal)');
  });

  it('sends the workspace it names and refreshes the list', async () => {
    const store = makeStore('t1');
    client.get.mockReturnValue(ok({ success: true }));
    prefApi.getConversations.mockResolvedValue({ data: [], loading: false });
    await store.dispatch(deleteAllChats(null, 't1'));
    expect(client.get).toHaveBeenCalledWith(
      '/api/delete_all_conversations',
      null,
      { [WORKSPACE_HEADER]: 't1' },
    );
    expect(prefApi.getConversations).toHaveBeenCalledTimes(1);
  });

  it('a refusal throws, for the dialog to show', async () => {
    const store = makeStore('t1');
    client.get.mockReturnValue(
      Promise.resolve(new Response('{}', { status: 500 })),
    );
    await expect(store.dispatch(deleteAllChats(null, 't1'))).rejects.toThrow();
  });
});

describe('the sidebar Team row', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    root = createRoot(container);
  });

  afterEach(() => act(() => root.unmount()));

  const render = (store: ReturnType<typeof makeStore>, go = vi.fn()) => {
    act(() => {
      root.render(
        <Provider store={store}>
          <MemoryRouter>
            <SidebarTeamEntry onNavigate={go} />
          </MemoryRouter>
        </Provider>,
      );
    });
    return go;
  };

  it("opens the current team's page in a team", () => {
    const go = render(makeStore('t1'));
    const link = container.querySelector('a');
    expect(link?.getAttribute('href')).toContain('/teams/t1');
    act(() => link?.click());
    expect(go).toHaveBeenCalledWith(expect.stringContaining('/teams/t1'));
  });

  it('is not there in Personal', () => {
    render(makeStore('personal'));
    expect(container.querySelector('a')).toBeNull();
  });
});
