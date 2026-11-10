import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi } from 'vitest';

const getFolders = vi.hoisted(() => vi.fn());
vi.mock('../../api/services/userService', () => ({
  default: { getFolders },
}));

import foldersReducer, {
  loadFolders,
  selectFolderList,
  selectFolders,
} from './foldersSlice';

const makeStore = () =>
  configureStore({ reducer: { folders: foldersReducer } });

const ok = (body: unknown) =>
  Promise.resolve({ ok: true, json: () => Promise.resolve(body) });

describe('foldersSlice', () => {
  it('keeps each type apart', async () => {
    getFolders.mockImplementation((type: string) =>
      ok({ folders: [{ id: type, name: type, parent_id: null }] }),
    );
    const store = makeStore();
    await store.dispatch(loadFolders({ type: 'agent', token: null }));
    expect(selectFolders('agent')(store.getState()).map((f) => f.id)).toEqual([
      'agent',
    ]);
    expect(selectFolderList('source')(store.getState()).loaded).toBe(false);
    expect(getFolders).toHaveBeenCalledWith('agent', null);
  });

  it('surfaces a failed load and keeps the last list', async () => {
    getFolders.mockImplementationOnce(() =>
      ok({ folders: [{ id: 'a', name: 'A', parent_id: null }] }),
    );
    const store = makeStore();
    await store.dispatch(loadFolders({ type: 'agent', token: null }));
    getFolders.mockImplementationOnce(() =>
      Promise.resolve({ ok: false, json: () => Promise.resolve({}) }),
    );
    const result = await store.dispatch(
      loadFolders({ type: 'agent', token: null }),
    );
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
    await store.dispatch(loadFolders({ type: 'agent', token: null }));
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

  it('reads a store without the slice as empty', () => {
    expect(selectFolders('agent')({})).toEqual([]);
    expect(selectFolderList('source')({}).loaded).toBe(false);
  });
});
