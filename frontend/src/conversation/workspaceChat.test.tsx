import { configureStore } from '@reduxjs/toolkit';
import { act, useEffect, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider, useSelector } from 'react-redux';
import {
  MemoryRouter,
  Outlet,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom';

vi.mock('i18next', () => ({
  default: { t: (key: string) => key, language: 'en' },
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.name ? `${key}(${String(opts.name)})` : key,
  }),
}));

import type { Agent } from '../agents/types';
import type { AccessFields } from '../utils/accessUtils';
import { prefSlice } from '../preferences/preferenceSlice';
import workspaceReducer, {
  loadWorkspaces,
  selectWorkspaceId,
  switchWorkspace,
} from '../workspace/workspaceSlice';
import { setRequestWorkspace } from '../workspace/requestWorkspace';
import useWorkspaceLanding from '../workspace/useWorkspaceLanding';
import ChatWorkspaceLine from './ChatWorkspaceLine';
import { curatedErrorText } from './curatedError';
import WorkspaceMismatchAction from './WorkspaceMismatchAction';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const ROWS = [
  { id: 'personal', kind: 'personal', name: 'Personal' },
  { id: 't1', kind: 'team', name: 'Operations', role: 'viewer' },
];

const agent = (workspace: AccessFields['workspace']): Agent =>
  ({
    id: 'a1',
    name: 'Carrier desk',
    workspace,
  }) as unknown as Agent;

const makeStore = (current: string, selected?: Agent) => {
  const store = configureStore({
    reducer: { workspace: workspaceReducer, preference: prefSlice.reducer },
  });
  store.dispatch({
    type: loadWorkspaces.fulfilled.type,
    payload: ROWS,
    meta: { requestId: null, arg: { token: null } },
  });
  if (current !== 'personal') store.dispatch(switchWorkspace(current));
  if (selected) store.dispatch(prefSlice.actions.setSelectedAgent(selected));
  return store;
};

let container: HTMLDivElement;
let root: Root;
let path = '';

function Where() {
  path = useLocation().pathname;
  return null;
}

/** Each page mount, as "<workspace> <path>". */
let mounts: string[] = [];

/** The app's layout: the page remounts on a switch, and lands after one. */
function Layout() {
  const workspace = useSelector(selectWorkspaceId);
  useWorkspaceLanding();
  return <Outlet key={workspace} />;
}

function Page({ node }: { node: ReactNode }) {
  const location = useLocation();
  const workspace = useSelector(selectWorkspaceId);
  useEffect(() => {
    mounts.push(`${workspace} ${location.pathname}`);
  }, []);
  return (
    <>
      {node}
      <Where />
    </>
  );
}

beforeEach(() => {
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

const render = (
  store: ReturnType<typeof makeStore>,
  node: ReactNode,
  at = '/c/new',
) =>
  act(() => {
    root.render(
      <Provider store={store}>
        <MemoryRouter initialEntries={[at]}>
          <Routes>
            <Route element={<Layout />}>
              <Route path="*" element={<Page node={node} />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </Provider>,
    );
  });

describe('a chat refused because its agent lives in another workspace', () => {
  it('says so in words', () => {
    const t = ((key: string) => key) as never;
    expect(curatedErrorText(t, 'raw', 'workspace_mismatch')).toBe(
      'workspace.chat.mismatch',
    );
    expect(curatedErrorText(t, 'raw', 'workspace_not_found')).toBe(
      'workspace.chat.notFound',
    );
  });

  it("offers to switch to the agent's team and opens its new chat", () => {
    const store = makeStore('personal', agent({ kind: 'team', team_id: 't1' }));
    render(store, <WorkspaceMismatchAction agentId="a1" />);
    const button = container.querySelector('button');
    expect(button?.textContent).toBe('workspace.chat.switchTo(Operations)');
    act(() => button?.click());
    expect(store.getState().workspace.current).toBe('t1');
    expect(path).toBe('/agents/a1/c/new');
  });

  it("switches only once the agent's new chat has rendered, so the old chat never reloads in the new workspace", () => {
    const store = makeStore('personal', agent({ kind: 'team', team_id: 't1' }));
    render(store, <WorkspaceMismatchAction agentId="a1" />, '/c/abc');
    mounts = [];
    act(() => container.querySelector('button')?.click());
    expect(store.getState().workspace.current).toBe('t1');
    expect(store.getState().workspace.lastReason).toBe('link');
    expect(mounts).toEqual(['t1 /agents/a1/c/new']);
  });

  it('offers Personal for a personal agent used in a team', () => {
    const store = makeStore('t1', agent({ kind: 'personal' }));
    render(store, <WorkspaceMismatchAction agentId="a1" />);
    expect(container.querySelector('button')?.textContent).toBe(
      'workspace.chat.switchTo(workspace.switcher.personal)',
    );
  });

  it("offers nothing for a team the caller isn't in", () => {
    const store = makeStore('personal', agent({ kind: 'team', team_id: 't9' }));
    render(store, <WorkspaceMismatchAction agentId="a1" />);
    expect(container.querySelector('button')).toBeNull();
  });
});

describe('the line under a chat composer', () => {
  it('in a team, names it and says the chat is private', () => {
    render(makeStore('t1'), <ChatWorkspaceLine />);
    expect(container.textContent).toContain('Operations');
    expect(container.textContent).toContain('workspace.chat.onlyYou');
  });

  it('takes a notice at its end', () => {
    render(makeStore('t1'), <ChatWorkspaceLine notice={<span>N</span>} />);
    expect(container.textContent?.endsWith('N')).toBe(true);
  });

  it('is not drawn in Personal', () => {
    render(makeStore('personal'), <ChatWorkspaceLine />);
    expect(container.textContent).toBe('');
  });
});
