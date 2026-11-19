import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

// Toasts read as their keys.
vi.mock('i18next', () => ({ default: { t: (key: string) => key } }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import actionToastReducer from '../notifications/actionToastSlice';
import { setRequestWorkspace } from './requestWorkspace';
import useFollowItemWorkspace from './useFollowItemWorkspace';
import { workspaceListenerMiddleware } from './workspaceListener';
import workspaceReducer, {
  loadWorkspaces,
  switchWorkspace,
} from './workspaceSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const ROWS = [
  { id: 'personal', kind: 'personal', name: 'Personal' },
  { id: 't1', kind: 'team', name: 'Operations', role: 'viewer' },
];

type ItemWorkspace = { kind: 'personal' | 'team'; team_id?: string | null };

const makeStore = (current = 'personal', loaded = true) => {
  const store = configureStore({
    reducer: { workspace: workspaceReducer, actionToast: actionToastReducer },
    middleware: (getDefault) =>
      getDefault().prepend(workspaceListenerMiddleware.middleware),
  });
  if (loaded)
    store.dispatch({
      type: loadWorkspaces.fulfilled.type,
      payload: ROWS,
      meta: { requestId: null, arg: { token: null } },
    });
  if (current !== 'personal') store.dispatch(switchWorkspace(current));
  return store;
};

function Follower({ workspace }: { workspace?: ItemWorkspace }) {
  useFollowItemWorkspace(workspace);
  return null;
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  localStorage.clear();
  container = document.createElement('div');
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  setRequestWorkspace('personal', 0);
});

const follow = (store: ReturnType<typeof makeStore>, ws?: ItemWorkspace) =>
  act(() => {
    root.render(
      <Provider store={store}>
        <Follower workspace={ws} />
      </Provider>,
    );
  });

describe('useFollowItemWorkspace', () => {
  it("switches to a team item's team and says so", () => {
    const store = makeStore('personal');
    follow(store, { kind: 'team', team_id: 't1' });
    expect(store.getState().workspace.current).toBe('t1');
    expect(store.getState().workspace.lastReason).toBe('link');
    expect(store.getState().actionToast.current?.message).toBe(
      'workspace.notices.switched',
    );
  });

  it('switches to Personal for a personal item opened in a team', () => {
    const store = makeStore('t1');
    follow(store, { kind: 'personal', team_id: null });
    expect(store.getState().workspace.current).toBe('personal');
  });

  it('does nothing when the item is already in the current workspace', () => {
    const store = makeStore('t1');
    const epoch = store.getState().workspace.epoch;
    follow(store, { kind: 'team', team_id: 't1' });
    expect(store.getState().workspace.epoch).toBe(epoch);
    expect(store.getState().actionToast.current).toBeNull();
  });

  it('does nothing for a team the caller is not in', () => {
    const store = makeStore('personal');
    follow(store, { kind: 'team', team_id: 't9' });
    expect(store.getState().workspace.current).toBe('personal');
  });

  it('does nothing without a workspace', () => {
    const store = makeStore('personal');
    follow(store, undefined);
    expect(store.getState().workspace.epoch).toBe(0);
  });

  it('waits for the workspace list before following a team', () => {
    const store = makeStore('personal', false);
    follow(store, { kind: 'team', team_id: 't1' });
    expect(store.getState().workspace.current).toBe('personal');
    act(() => {
      store.dispatch({
        type: loadWorkspaces.fulfilled.type,
        payload: ROWS,
        meta: { requestId: null, arg: { token: null } },
      });
    });
    expect(store.getState().workspace.current).toBe('t1');
  });
});
