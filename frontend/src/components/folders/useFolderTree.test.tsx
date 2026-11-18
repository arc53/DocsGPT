import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

const getFolders = vi.hoisted(() => vi.fn());
vi.mock('../../api/services/userService', () => ({
  default: { getFolders },
}));

import {
  PERSONAL_WORKSPACE,
  setRequestWorkspace,
} from '../../workspace/requestWorkspace';
import { switchWorkspace } from '../../workspace/workspaceSlice';
import foldersReducer, { selectFolderTree } from './foldersSlice';
import { useFolderTree, type UseFolderTree } from './useFolderTree';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;
let latest: UseFolderTree;
const seen: UseFolderTree['tree'][] = [];

function Consumer() {
  latest = useFolderTree();
  seen.push(latest.tree);
  return null;
}

const makeStore = () =>
  configureStore({
    reducer: {
      preference: () => ({ token: 'tok' }),
      folders: foldersReducer,
    },
  });

const answer = (ids: string[]) => ({
  ok: true,
  json: () =>
    Promise.resolve({
      folders: ids.map((id) => ({ id, name: id, parent_id: null })),
    }),
});

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  getFolders.mockReset();
  seen.length = 0;
  setRequestWorkspace(PERSONAL_WORKSPACE, 0);
});

describe('useFolderTree', () => {
  it('asks for the tree once when several screens mount together', async () => {
    getFolders.mockImplementation(() => Promise.resolve(answer(['a'])));
    const store = makeStore();
    await act(async () => {
      root.render(
        <Provider store={store}>
          <Consumer />
          <Consumer />
          <Consumer />
        </Provider>,
      );
    });
    expect(getFolders).toHaveBeenCalledTimes(1);
    expect(selectFolderTree(store.getState()).items.map((f) => f.id)).toEqual([
      'a',
    ]);
  });

  it('reloads on request even while a load is out, and the reload wins', async () => {
    let releaseFirst: (value: unknown) => void = () => undefined;
    getFolders
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            releaseFirst = resolve;
          }),
      )
      .mockImplementationOnce(() => Promise.resolve(answer(['after'])));
    const store = makeStore();
    await act(async () => {
      root.render(
        <Provider store={store}>
          <Consumer />
        </Provider>,
      );
    });
    expect(getFolders).toHaveBeenCalledTimes(1);
    // A change was made while the first load was out: it must not be skipped.
    await act(async () => latest.reload());
    expect(getFolders).toHaveBeenCalledTimes(2);
    await act(async () => releaseFirst(answer(['before'])));
    expect(selectFolderTree(store.getState()).items.map((f) => f.id)).toEqual([
      'after',
    ]);
  });

  it("loads the new workspace's tree after a switch while a load is out", async () => {
    let releaseOld: (value: unknown) => void = () => undefined;
    getFolders
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            releaseOld = resolve;
          }),
      )
      .mockImplementationOnce(() => Promise.resolve(answer(['team'])));
    const store = makeStore();
    await act(async () => {
      root.render(
        <Provider store={store}>
          <Consumer />
          <Consumer />
        </Provider>,
      );
    });
    expect(getFolders).toHaveBeenCalledTimes(1);
    await act(async () => {
      setRequestWorkspace('t1', 1);
      store.dispatch(switchWorkspace('t1'));
    });
    expect(getFolders).toHaveBeenCalledTimes(2);
    // The Personal answer arrives last and must not replace the team's tree.
    await act(async () => releaseOld(answer(['mine'])));
    const list = selectFolderTree(store.getState());
    expect(list.items.map((f) => f.id)).toEqual(['team']);
    expect(list.loaded).toBe(true);
  });

  it('builds the tree once for every screen that reads it', async () => {
    getFolders.mockImplementation(() => Promise.resolve(answer(['b', 'a'])));
    const store = makeStore();
    await act(async () => {
      root.render(
        <Provider store={store}>
          <Consumer />
          <Consumer />
        </Provider>,
      );
    });
    const [first, second] = seen.slice(-2);
    expect(first).toBe(second);
    expect(first.children.get(null)?.map((f) => f.id)).toEqual(['a', 'b']);
  });
});
