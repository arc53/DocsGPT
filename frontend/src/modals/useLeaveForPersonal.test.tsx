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

import { prefSlice } from '../preferences/preferenceSlice';
import { setRequestWorkspace } from '../workspace/requestWorkspace';
import useWorkspaceLanding from '../workspace/useWorkspaceLanding';
import workspaceReducer, {
  loadWorkspaces,
  selectWorkspaceId,
  switchWorkspace,
} from '../workspace/workspaceSlice';
import useLeaveForPersonal from './useLeaveForPersonal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const makeStore = () => {
  const store = configureStore({
    reducer: { workspace: workspaceReducer, preference: prefSlice.reducer },
  });
  store.dispatch({
    type: loadWorkspaces.fulfilled.type,
    payload: [
      { id: 'personal', kind: 'personal', name: 'Personal' },
      { id: 't1', kind: 'team', name: 'Operations', role: 'admin' },
    ],
    meta: { requestId: null, arg: { token: null } },
  });
  store.dispatch(switchWorkspace('t1'));
  return store;
};

/** Each page render at a new location, as "<workspace> <path> <state.newMcpServer.name>". */
let mounts: string[] = [];

/** The app's layout: the page remounts on a switch, and lands after one. */
function Layout() {
  const workspace = useSelector(selectWorkspaceId);
  useWorkspaceLanding();
  return <Outlet key={workspace} />;
}

function Page() {
  const location = useLocation();
  const workspace = useSelector(selectWorkspaceId);
  const leave = useLeaveForPersonal();
  const state = location.state as {
    newMcpServer?: { name: string };
  } | null;
  // Each location each mount sees.
  useEffect(() => {
    mounts.push(
      `${workspace} ${location.pathname} ${state?.newMcpServer?.name ?? '-'}`,
    );
  }, [location.key]);
  return (
    <button
      type="button"
      onClick={() =>
        leave('/settings/tools', { newMcpServer: { name: 'Ops MCP' } })
      }
    />
  );
}

describe('useLeaveForPersonal', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    mounts = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    setRequestWorkspace('personal', 0);
    localStorage.clear();
  });

  const render = (store: ReturnType<typeof makeStore>, at: string) =>
    act(() => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={[at]}>
            <Routes>
              <Route element={<Layout />}>
                <Route path="*" element={<Page />} />
              </Route>
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });

  it('leaves a team chat for Personal without the chat reloading in Personal, which would follow it back to the team', () => {
    const store = makeStore();
    render(store, '/c/abc');
    mounts = [];
    act(() => container.querySelector('button')?.click());
    expect(store.getState().workspace.current).toBe('personal');
    expect(mounts).not.toContain('personal /c/abc -');
    expect(mounts[mounts.length - 1]).toBe('personal /settings/tools Ops MCP');
  });

  it('leaves a team list page for Personal with what the page is opened with', () => {
    const store = makeStore();
    render(store, '/settings/tools');
    mounts = [];
    act(() => container.querySelector('button')?.click());
    expect(store.getState().workspace.current).toBe('personal');
    expect(mounts[mounts.length - 1]).toBe('personal /settings/tools Ops MCP');
  });
});
