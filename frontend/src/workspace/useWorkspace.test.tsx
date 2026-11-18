import { configureStore } from '@reduxjs/toolkit';
import { act, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider, useSelector } from 'react-redux';
import {
  MemoryRouter,
  Outlet,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom';

// Toasts read as their keys.
vi.mock('i18next', () => ({ default: { t: (key: string) => key } }));

import actionToastReducer from '../notifications/actionToastSlice';
import { setRequestWorkspace } from './requestWorkspace';
import useWorkspace from './useWorkspace';
import useWorkspaceLanding from './useWorkspaceLanding';
import { workspaceListenerMiddleware } from './workspaceListener';
import workspaceReducer, {
  loadWorkspaces,
  selectWorkspaceId,
  switchWorkspace,
} from './workspaceSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const ROWS = [
  { id: 'personal', kind: 'personal', name: 'Personal' },
  { id: 't1', kind: 'team', name: 'Operations', role: 'admin' },
];

let container: HTMLDivElement;
let root: Root;
/** Each page mount, as "<workspace> <path>". */
let mounts: string[] = [];
let where: { path: string; state: unknown } = { path: '', state: null };

function Page() {
  const location = useLocation();
  const workspace = useSelector(selectWorkspaceId);
  useEffect(() => {
    mounts.push(`${workspace} ${location.pathname}`);
  }, []);
  return null;
}

/** The app's layout: the page remounts on a switch, and lands after one. */
function Layout() {
  const workspace = useSelector(selectWorkspaceId);
  useWorkspaceLanding();
  return <Outlet key={workspace} />;
}

function Where() {
  const location = useLocation();
  where = {
    path: `${location.pathname}${location.search}`,
    state: location.state,
  };
  return null;
}

let switchTo: (id: string) => void = () => undefined;
function Switcher() {
  switchTo = useWorkspace().switchTo;
  return null;
}

const listLoaded = (rows = ROWS) => ({
  type: loadWorkspaces.fulfilled.type,
  payload: rows,
  meta: { requestId: null, arg: { token: null } },
});

const makeStore = (current = 'personal', loaded = true) => {
  const store = configureStore({
    reducer: { workspace: workspaceReducer, actionToast: actionToastReducer },
    middleware: (getDefault) =>
      getDefault().prepend(workspaceListenerMiddleware.middleware),
  });
  if (loaded) store.dispatch(listLoaded());
  if (current !== 'personal') store.dispatch(switchWorkspace(current));
  return store;
};

const render = (store: ReturnType<typeof makeStore>, at: string) =>
  act(() => {
    root.render(
      <Provider store={store}>
        <MemoryRouter initialEntries={[at]}>
          <Switcher />
          <Where />
          <Routes>
            <Route element={<Layout />}>
              <Route path="/c/:id" element={<Page />} />
              <Route path="/agents/*" element={<Page />} />
              <Route path="/settings/*" element={<Page />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </Provider>,
    );
  });

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  mounts = [];
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  setRequestWorkspace('personal', 0);
  localStorage.clear();
});

describe('switching workspace from the switcher', () => {
  it("leaves an open chat before the switch, so the page never remounts on the old chat's address", () => {
    const store = makeStore();
    render(store, '/c/abc');
    mounts = [];
    act(() => switchTo('t1'));
    expect(store.getState().workspace.current).toBe('t1');
    expect(where.path).toBe('/c/new');
    expect(mounts).toEqual(['t1 /c/new']);
  });

  it("leaves an item's page for its list before the switch", () => {
    const store = makeStore();
    render(store, '/agents/manage/edit/a1');
    mounts = [];
    act(() => switchTo('t1'));
    expect(where.path).toBe('/agents/manage');
    expect(mounts).toEqual(['t1 /agents/manage']);
  });

  it('forgets the switch it asked for once done, so Back or a reload does not switch again', () => {
    const store = makeStore();
    render(store, '/c/abc');
    act(() => switchTo('t1'));
    expect(where.state).toBeNull();
    expect(store.getState().workspace.epoch).toBe(1);
  });

  it('switches at once on a list page', () => {
    const store = makeStore('t1');
    render(store, '/settings/tools');
    mounts = [];
    act(() => switchTo('personal'));
    expect(store.getState().workspace.current).toBe('personal');
    expect(where.path).toBe('/settings/tools');
    expect(mounts).toEqual(['personal /settings/tools']);
  });
});

describe('a team that turns out gone', () => {
  it('keeps a page opened by its address when the stored team is gone at start', () => {
    // The last visit was in t9, which the caller has since left.
    const store = makeStore('t9', false);
    render(store, '/c/abc');
    mounts = [];
    act(() => {
      store.dispatch(listLoaded());
    });
    expect(store.getState().workspace.current).toBe('personal');
    expect(where.path).toBe('/c/abc');
    // The page loads again in Personal; a chat of the gone team says so.
    expect(mounts).toEqual(['personal /c/abc']);
  });

  it('lands the page on its list when a team confirmed earlier goes', () => {
    const store = makeStore('t1');
    render(store, '/c/abc');
    mounts = [];
    act(() => {
      store.dispatch(listLoaded([ROWS[0]]));
    });
    expect(store.getState().workspace.current).toBe('personal');
    expect(where.path).toBe('/c/new');
  });
});
