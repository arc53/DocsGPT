import { configureStore } from '@reduxjs/toolkit';
import { afterEach, describe, expect, it, vi } from 'vitest';

const getFolders = vi.hoisted(() => vi.fn());
vi.mock('../../api/services/userService', () => ({
  default: { getFolders },
}));

import {
  PERSONAL_WORKSPACE,
  setRequestWorkspace,
} from '../../workspace/requestWorkspace';
import { switchWorkspace } from '../../workspace/workspaceSlice';
import foldersReducer, {
  folderRemoved,
  loadFolders,
  selectFolderList,
  selectFolderTree,
  selectFolders,
} from './foldersSlice';

const makeStore = () =>
  configureStore({ reducer: { folders: foldersReducer } });

const ok = (body: unknown) =>
  Promise.resolve({ ok: true, json: () => Promise.resolve(body) });

afterEach(() => {
  getFolders.mockReset();
  setRequestWorkspace(PERSONAL_WORKSPACE, 0);
});

describe('foldersSlice', () => {
  it('loads one tree, the same for every kind', async () => {
    getFolders.mockImplementation(() =>
      ok({ folders: [{ id: 'f1', name: 'Onboarding', parent_id: null }] }),
    );
    const store = makeStore();
    await store.dispatch(loadFolders({ type: 'agent', token: 'tok' }));
    // The whole tree is asked for: no kind narrows it.
    expect(getFolders).toHaveBeenCalledWith('tok');
    for (const kind of ['agent', 'source', 'tool', 'prompt'] as const) {
      expect(selectFolders(kind)(store.getState()).map((f) => f.id)).toEqual([
        'f1',
      ]);
      expect(selectFolderList(kind)(store.getState()).loaded).toBe(true);
    }
    expect(selectFolderTree(store.getState()).items).toHaveLength(1);
  });

  it('loads without a kind', async () => {
    getFolders.mockImplementation(() => ok({ folders: [] }));
    const store = makeStore();
    await store.dispatch(loadFolders({ token: null }));
    expect(selectFolderTree(store.getState()).loaded).toBe(true);
  });

  it('surfaces a failed load and keeps the last list', async () => {
    getFolders.mockImplementationOnce(() =>
      ok({ folders: [{ id: 'a', name: 'A', parent_id: null }] }),
    );
    const store = makeStore();
    await store.dispatch(loadFolders({ token: null }));
    getFolders.mockImplementationOnce(() =>
      Promise.resolve({ ok: false, json: () => Promise.resolve({}) }),
    );
    const result = await store.dispatch(loadFolders({ token: null }));
    expect(result.meta.requestStatus).toBe('rejected');
    const list = selectFolderList('agent')(store.getState());
    expect(list.failed).toBe(true);
    expect(list.items.map((f) => f.id)).toEqual(['a']);
  });

  it('applies only the load started last', async () => {
    let releaseFirst: (value: unknown) => void = () => undefined;
    getFolders
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            releaseFirst = resolve;
          }),
      )
      .mockImplementationOnce(() =>
        ok({ folders: [{ id: 'new', name: 'New', parent_id: null }] }),
      );
    const store = makeStore();
    const first = store.dispatch(loadFolders({ type: 'agent', token: null }));
    await store.dispatch(loadFolders({ type: 'source', token: null }));
    releaseFirst({
      ok: true,
      json: () =>
        Promise.resolve({
          folders: [{ id: 'old', name: 'Old', parent_id: null }],
        }),
    });
    await first;
    expect(selectFolders('agent')(store.getState()).map((f) => f.id)).toEqual([
      'new',
    ]);
  });

  it('drops an answer from the workspace the app has left', async () => {
    let release: (value: unknown) => void = () => undefined;
    getFolders.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    const store = makeStore();
    const pending = store.dispatch(loadFolders({ token: null }));
    // The switch lands while the Personal load is still out.
    setRequestWorkspace('t1', 1);
    store.dispatch(switchWorkspace('t1'));
    release({
      ok: true,
      json: () =>
        Promise.resolve({
          folders: [{ id: 'mine', name: 'Mine', parent_id: null }],
        }),
    });
    const result = await pending;
    expect(result.meta.requestStatus).toBe('rejected');
    const list = selectFolderTree(store.getState());
    expect(list.items).toEqual([]);
    expect(list.loaded).toBe(false);
    expect(list.failed).toBe(false);
  });

  it('drops a stale answer even when no switch reached the slice', async () => {
    let release: (value: unknown) => void = () => undefined;
    getFolders.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    const store = makeStore();
    const pending = store.dispatch(loadFolders({ token: null }));
    setRequestWorkspace('t1', 1);
    release({
      ok: true,
      json: () =>
        Promise.resolve({
          folders: [{ id: 'mine', name: 'Mine', parent_id: null }],
        }),
    });
    await pending;
    expect(selectFolderTree(store.getState()).items).toEqual([]);
    expect(selectFolderTree(store.getState()).failed).toBe(false);
  });

  it('drops a deleted folder and remembers where its contents went', async () => {
    getFolders.mockImplementation(() =>
      ok({
        folders: [
          { id: 'p', name: 'P', parent_id: null },
          { id: 'c', name: 'C', parent_id: 'p' },
        ],
      }),
    );
    const store = makeStore();
    await store.dispatch(loadFolders({ token: null }));
    store.dispatch(folderRemoved({ id: 'c', parentId: 'p' }));
    const list = selectFolderTree(store.getState());
    expect(list.items.map((f) => f.id)).toEqual(['p']);
    expect(list.removedParents).toEqual({ c: 'p' });
  });

  it('reads a store without the slice as empty', () => {
    expect(selectFolders('agent')({})).toEqual([]);
    expect(selectFolderList('source')({}).loaded).toBe(false);
    expect(selectFolderTree({}).loaded).toBe(false);
  });
});
