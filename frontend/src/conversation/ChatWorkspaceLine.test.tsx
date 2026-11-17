import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.team ? `${key}(${String(opts.team)})` : key,
  }),
}));

import workspaceReducer, {
  loadWorkspaces,
  switchWorkspace,
  type WorkspaceRow,
} from '../workspace/workspaceSlice';
import { setRequestWorkspace } from '../workspace/requestWorkspace';
import ChatWorkspaceLine from './ChatWorkspaceLine';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const makeStore = (current: string, chatExport: boolean | undefined) => {
  const store = configureStore({ reducer: { workspace: workspaceReducer } });
  const rows: WorkspaceRow[] = [
    { id: 'personal', kind: 'personal', name: 'Personal' },
    {
      id: 't1',
      kind: 'team',
      name: 'Operations',
      role: 'viewer',
      ...(chatExport === undefined ? {} : { chat_export: chatExport }),
    },
  ];
  store.dispatch({
    type: loadWorkspaces.fulfilled.type,
    payload: rows,
    meta: { requestId: null, arg: { token: null } },
  });
  if (current !== 'personal') store.dispatch(switchWorkspace(current));
  return store;
};

let container: HTMLDivElement;
let root: Root;

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

const render = (store: ReturnType<typeof makeStore>) =>
  act(() => {
    root.render(
      <Provider store={store}>
        <ChatWorkspaceLine />
      </Provider>,
    );
  });

const line = () =>
  container.querySelector('[data-testid="chat-workspace-line"]');

describe('the workspace line under the composer', () => {
  it('names only the team when its admins can export chats', () => {
    render(makeStore('t1', true));
    expect(line()?.textContent).toBe('Operations');
    // The chat isn't only theirs to see any more.
    expect(line()?.textContent).not.toContain('workspace.chat.onlyYou');
  });

  it('keeps "Only you can see this chat" while the setting is off', () => {
    render(makeStore('t1', false));
    expect(line()?.textContent).toContain('Operations');
    expect(line()?.textContent).toContain('workspace.chat.onlyYou');
  });

  it('reads an older server with no setting as off', () => {
    render(makeStore('t1', undefined));
    expect(line()?.textContent).toContain('workspace.chat.onlyYou');
  });

  it('says nothing in Personal', () => {
    render(makeStore('personal', true));
    expect(line()).toBeNull();
  });
});
