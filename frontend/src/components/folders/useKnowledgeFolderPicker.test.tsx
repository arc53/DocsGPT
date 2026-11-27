import { configureStore } from '@reduxjs/toolkit';
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options && 'name' in options ? `${key}:${options.name}` : key,
  }),
}));

const api = vi.hoisted(() => ({ getFolders: vi.fn() }));
vi.mock('../../api/services/userService', () => ({ default: api }));

import type { Doc } from '../../models/misc';
import type { KnowledgePick } from './folderPick';
import { folderRowId } from './folderPick';
import foldersReducer, { type FolderListState } from './foldersSlice';
import type { Folder } from './types';
import { useKnowledgeFolderPicker } from './useKnowledgeFolderPicker';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const folders: Folder[] = [
  { id: 'carriers', name: 'Carriers', parent_id: null, item_count: 1 },
  { id: 'rates', name: 'Rate archive', parent_id: 'carriers', item_count: 1 },
];
const docs = [
  { id: 'q4', name: 'Q4', date: '', model: '', folder_id: 'carriers' },
  { id: 'r25', name: 'Rates 2025', date: '', model: '', folder_id: 'rates' },
] as Doc[];

const json = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

const tree = (over: Partial<FolderListState> = {}): FolderListState => ({
  items: folders,
  loaded: true,
  loading: false,
  failed: false,
  latestRequestId: null,
  removedParents: {},
  ...over,
});

let container: HTMLDivElement;
let root: Root;
let popover: ReturnType<typeof useKnowledgeFolderPicker>['popoverProps'];

function Harness({ initial }: { initial: KnowledgePick }) {
  const [pick, setPick] = useState(initial);
  popover = useKnowledgeFolderPicker({
    open: true,
    docs,
    pick,
    onPickChange: setPick,
    connections: [],
  }).popoverProps;
  return <>{popover.header}</>;
}

const mount = async (initial: KnowledgePick, list = tree()) => {
  const store = configureStore({
    reducer: {
      preference: () => ({ token: 'tok' }),
      folders: foldersReducer,
    },
    preloadedState: { folders: { tree: list } },
  });
  await act(async () => {
    root.render(
      <Provider store={store}>
        <Harness initial={initial} />
      </Provider>,
    );
  });
  return store;
};

beforeEach(() => {
  api.getFolders.mockReset();
  api.getFolders.mockImplementation(() => json({ folders }));
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

const pinnedIds = () =>
  (popover.items ?? []).filter((row) => row.pinnedOnly).map((row) => row.id);

describe('useKnowledgeFolderPicker', () => {
  it('keeps a pinned subfolder and filed source at the root after unticking them', async () => {
    await mount({ sources: ['q4'], folders: ['rates'] });
    expect(pinnedIds()).toEqual([folderRowId('rates'), 'q4']);
    await act(async () => popover.onToggle(folderRowId('rates')));
    await act(async () => popover.onToggle('q4'));
    expect(popover.selectedIds).toEqual([]);
    // Still listed, unticked: no row moves under the pointer.
    expect(pinnedIds()).toEqual([folderRowId('rates'), 'q4']);
  });

  it('says the folders failed to load, with Retry that loads them again', async () => {
    // The load each open asks for fails too.
    api.getFolders.mockImplementationOnce(() => json({}, false, 500));
    const store = await mount(
      { sources: [], folders: [] },
      tree({ items: [], loaded: false, failed: true }),
    );
    expect(container.textContent).toContain('folders.errors.loadFailed');
    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(api.getFolders).toHaveBeenCalledWith('tok');
    expect(store.getState().folders.tree.items).toEqual(folders);
  });
});
