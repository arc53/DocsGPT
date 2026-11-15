import { configureStore } from '@reduxjs/toolkit';

const list = vi.hoisted(() => vi.fn());
vi.mock('../api/services/workspacesService', () => ({
  default: { list: (...args: unknown[]) => list(...args) },
}));

// Toasts read as their keys.
vi.mock('i18next', () => ({ default: { t: (key: string) => key } }));

const STORAGE_KEY = 'DocsGPTWorkspace';

const PERSONAL_ROW = { id: 'personal', kind: 'personal', name: 'Personal' };
const OPS = {
  id: 't1',
  kind: 'team',
  name: 'Operations',
  slug: 'operations',
  role: 'admin',
  member_count: 12,
  principal_label: 'Operations',
};
const SALES = {
  id: 't2',
  kind: 'team',
  name: 'Sales',
  slug: 'sales',
  role: 'viewer',
  member_count: 8,
  principal_label: 'Sales',
};

/** The slice and its listener, fresh: the stored id is read at module load. */
const load = async () => {
  vi.resetModules();
  const slice = await import('./workspaceSlice');
  const listener = await import('./workspaceListener');
  const request = await import('./requestWorkspace');
  const toast = await import('../notifications/actionToastSlice');
  const store = configureStore({
    reducer: { workspace: slice.default, actionToast: toast.default },
    middleware: (getDefault) =>
      getDefault().prepend(listener.workspaceListenerMiddleware.middleware),
  });
  return { slice, request, listener, store };
};

beforeEach(() => {
  localStorage.clear();
  list.mockReset();
});

describe('workspace slice: where the app starts', () => {
  it('starts in Personal with nothing stored', async () => {
    const { slice, request, store } = await load();
    expect(slice.selectWorkspaceId(store.getState())).toBe('personal');
    expect(slice.selectIsTeamWorkspace(store.getState())).toBe(false);
    expect(request.requestWorkspace()).toBe('personal');
  });

  it('restores the stored workspace, and requests start there', async () => {
    localStorage.setItem(STORAGE_KEY, 't1');
    const { slice, request, store } = await load();
    expect(slice.selectWorkspaceId(store.getState())).toBe('t1');
    expect(slice.selectIsTeamWorkspace(store.getState())).toBe(true);
    expect(request.requestWorkspace()).toBe('t1');
  });

  it('migrates the old currentTeamId once', async () => {
    localStorage.setItem('currentTeamId', 't9');
    const { slice, store } = await load();
    expect(slice.selectWorkspaceId(store.getState())).toBe('t9');
    expect(localStorage.getItem(STORAGE_KEY)).toBe('t9');
    expect(localStorage.getItem('currentTeamId')).toBeNull();
  });

  it('prefers the new key over a leftover currentTeamId', async () => {
    localStorage.setItem(STORAGE_KEY, 'personal');
    localStorage.setItem('currentTeamId', 't9');
    const { slice, store } = await load();
    expect(slice.selectWorkspaceId(store.getState())).toBe('personal');
  });
});

describe('workspace slice: switching', () => {
  it('persists the switch, bumps the epoch and moves requests at once', async () => {
    const { slice, request, store } = await load();
    const before = store.getState().workspace.epoch;
    store.dispatch(slice.switchWorkspace('t1'));
    expect(store.getState().workspace.current).toBe('t1');
    expect(store.getState().workspace.epoch).toBe(before + 1);
    expect(localStorage.getItem(STORAGE_KEY)).toBe('t1');
    // Synchronously: the remount that follows fetches with the new header.
    expect(request.requestWorkspace()).toBe('t1');
  });

  it('records why it switched', async () => {
    const { slice, store } = await load();
    const action = slice.switchWorkspace('t1', { reason: 'link' });
    expect(action.type).toBe('workspace/switched');
    expect(action.payload).toEqual({ id: 't1', reason: 'link' });
    store.dispatch(action);
    expect(store.getState().workspace.lastReason).toBe('link');
    expect(slice.switchWorkspace('personal').payload.reason).toBe('user');
  });

  it('bumps the epoch even when switching back', async () => {
    const { slice, store } = await load();
    store.dispatch(slice.switchWorkspace('t1'));
    store.dispatch(slice.switchWorkspace('personal'));
    expect(store.getState().workspace.epoch).toBe(2);
    expect(localStorage.getItem(STORAGE_KEY)).toBe('personal');
  });

  it("ignores another tab's switch (storage events)", async () => {
    const { slice, request, store } = await load();
    localStorage.setItem(STORAGE_KEY, 't2');
    window.dispatchEvent(
      new StorageEvent('storage', { key: STORAGE_KEY, newValue: 't2' }),
    );
    expect(slice.selectWorkspaceId(store.getState())).toBe('personal');
    expect(request.requestWorkspace()).toBe('personal');
  });
});

describe('workspace slice: the list from /api/workspaces', () => {
  it('loads the rows and keeps a listed team', async () => {
    localStorage.setItem(STORAGE_KEY, 't1');
    list.mockResolvedValue([PERSONAL_ROW, OPS, SALES]);
    const { slice, store } = await load();
    expect(slice.selectWorkspacesLoaded(store.getState())).toBe(false);
    await store.dispatch(slice.loadWorkspaces({ token: 'tok' }));
    const state = store.getState();
    expect(list).toHaveBeenCalledWith({ token: 'tok' });
    expect(slice.selectWorkspacesLoaded(state)).toBe(true);
    expect(slice.selectWorkspaces(state)).toHaveLength(3);
    expect(slice.selectWorkspaceId(state)).toBe('t1');
    expect(slice.selectCurrentWorkspace(state).name).toBe('Operations');
    expect(slice.selectWorkspaceRole(state)).toBe('admin');
    expect(state.actionToast.current).toBeNull();
  });

  it('drops a team the caller is no longer in, back to Personal, with a toast', async () => {
    localStorage.setItem(STORAGE_KEY, 't1');
    list.mockResolvedValue([PERSONAL_ROW, SALES]);
    const { slice, request, store } = await load();
    const epoch = store.getState().workspace.epoch;
    await store.dispatch(slice.loadWorkspaces({ token: 'tok' }));
    const state = store.getState();
    expect(slice.selectWorkspaceId(state)).toBe('personal');
    expect(state.workspace.epoch).toBe(epoch + 1);
    expect(state.workspace.lastReason).toBe('lost');
    expect(localStorage.getItem(STORAGE_KEY)).toBe('personal');
    expect(request.requestWorkspace()).toBe('personal');
    // No earlier list named the team, so the toast can't either.
    expect(state.actionToast.current?.message).toBe(
      'workspace.notices.lostUnnamed',
    );
  });

  it('names the lost team when an earlier list knew it', async () => {
    localStorage.setItem(STORAGE_KEY, 't1');
    list.mockResolvedValueOnce([PERSONAL_ROW, OPS]);
    list.mockResolvedValueOnce([PERSONAL_ROW]);
    const { slice, store } = await load();
    await store.dispatch(slice.loadWorkspaces({ token: 'tok' }));
    await store.dispatch(slice.loadWorkspaces({ token: 'tok' }));
    expect(store.getState().actionToast.current?.message).toBe(
      'workspace.notices.lost',
    );
    expect(slice.selectWorkspaceId(store.getState())).toBe('personal');
  });

  it('keeps the stored team when the list fails to load', async () => {
    localStorage.setItem(STORAGE_KEY, 't1');
    list.mockRejectedValue(new Error('down'));
    const { slice, store } = await load();
    await store.dispatch(slice.loadWorkspaces({ token: 'tok' }));
    expect(slice.selectWorkspaceId(store.getState())).toBe('t1');
    expect(slice.selectWorkspacesLoaded(store.getState())).toBe(false);
  });

  it('applies only the latest of two overlapping loads', async () => {
    let resolveFirst: (rows: unknown) => void = () => undefined;
    list.mockImplementationOnce(
      () => new Promise((resolve) => (resolveFirst = resolve)),
    );
    list.mockResolvedValueOnce([PERSONAL_ROW, OPS, SALES]);
    const { slice, store } = await load();
    const first = store.dispatch(slice.loadWorkspaces({ token: 'tok' }));
    await store.dispatch(slice.loadWorkspaces({ token: 'tok' }));
    resolveFirst([PERSONAL_ROW]);
    await first;
    expect(slice.selectWorkspaces(store.getState())).toHaveLength(3);
  });
});

describe('workspace selectors', () => {
  it('reads Personal as the owner, who may create', async () => {
    const { slice, store } = await load();
    const state = store.getState();
    expect(slice.selectWorkspaceRole(state)).toBe('owner');
    expect(slice.selectCanCreateInWorkspace(state)).toBe(true);
    expect(slice.selectCurrentWorkspace(state).kind).toBe('personal');
  });

  it('lets an Editor create in a team, never a Viewer', async () => {
    localStorage.setItem(STORAGE_KEY, 't2');
    list.mockResolvedValue([
      PERSONAL_ROW,
      OPS,
      SALES,
      { ...OPS, id: 't3', role: 'editor' },
    ]);
    const { slice, store } = await load();
    await store.dispatch(slice.loadWorkspaces({ token: null }));
    expect(slice.selectWorkspaceRole(store.getState())).toBe('viewer');
    expect(slice.selectCanCreateInWorkspace(store.getState())).toBe(false);
    store.dispatch(slice.switchWorkspace('t3'));
    expect(slice.selectCanCreateInWorkspace(store.getState())).toBe(true);
  });

  it('reads a team as a Viewer until the list says otherwise', async () => {
    localStorage.setItem(STORAGE_KEY, 't1');
    const { slice, store } = await load();
    const state = store.getState();
    expect(slice.selectWorkspaceRole(state)).toBe('viewer');
    expect(slice.selectCanCreateInWorkspace(state)).toBe(false);
    expect(slice.selectCurrentWorkspace(state)).toMatchObject({
      id: 't1',
      kind: 'team',
    });
  });
});

describe('workspace refusals the API client reports', () => {
  it('checks the list again on a 404 workspace_not_found, then drops to Personal', async () => {
    localStorage.setItem(STORAGE_KEY, 't1');
    list.mockResolvedValue([PERSONAL_ROW, SALES]);
    const { slice, request, listener, store } = await load();
    const off = listener.connectWorkspaceClient(store);
    request.reportWorkspaceRefusal(404, 'workspace_not_found', 't1');
    await vi.waitFor(() =>
      expect(slice.selectWorkspaceId(store.getState())).toBe('personal'),
    );
    expect(list).toHaveBeenCalledTimes(1);
    off();
  });

  it('ignores one for a workspace the app has already left', async () => {
    localStorage.setItem(STORAGE_KEY, 't1');
    const { request, listener, store } = await load();
    const off = listener.connectWorkspaceClient(store);
    request.reportWorkspaceRefusal(404, 'workspace_not_found', 't2');
    request.reportWorkspaceRefusal(404, 'workspace_not_found', 'personal');
    expect(list).not.toHaveBeenCalled();
    off();
  });

  it('says the role changed on a 403 workspace_role_required and reloads it', async () => {
    localStorage.setItem(STORAGE_KEY, 't2');
    list.mockResolvedValue([PERSONAL_ROW, SALES]);
    const { slice, request, listener, store } = await load();
    const off = listener.connectWorkspaceClient(store);
    request.reportWorkspaceRefusal(403, 'workspace_role_required', 't2');
    expect(store.getState().actionToast.current?.message).toBe(
      'workspace.notices.roleChanged',
    );
    await vi.waitFor(() =>
      expect(slice.selectWorkspacesLoaded(store.getState())).toBe(true),
    );
    expect(slice.selectWorkspaceId(store.getState())).toBe('t2');
    off();
  });
});
