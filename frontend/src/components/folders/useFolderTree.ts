import { useCallback, useEffect, useMemo } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { selectToken } from '../../preferences/preferenceSlice';
import type { AppDispatch } from '../../store';
import {
  type FolderListState,
  loadFolders,
  selectFolderTree,
} from './foldersSlice';
import { buildFolderTree, type FolderTree } from './folderTree';

export type UseFolderTree = {
  /** The tree's folders and where its load stands. */
  list: FolderListState;
  tree: FolderTree;
  loaded: boolean;
  /** Load it again (after a change made elsewhere). */
  reload: () => void;
};

/**
 * The current workspace's folder tree, loaded once when nothing has asked
 * yet; every page and picker reads the same copy. A failed load stays failed
 * until `reload` (pages show it with Retry).
 */
export function useFolderTree(): UseFolderTree {
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const list = useSelector(selectFolderTree);
  const tree = useMemo(() => buildFolderTree(list.items), [list.items]);
  const reload = useCallback(
    () => void dispatch(loadFolders({ token, force: true })),
    [dispatch, token],
  );
  useEffect(() => {
    if (!list.loaded && !list.loading && !list.failed)
      void dispatch(loadFolders({ token }));
  }, [list.loaded, list.loading, list.failed, dispatch, token]);
  return { list, tree, loaded: list.loaded, reload };
}
