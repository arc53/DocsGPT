import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useSearchParams } from 'react-router-dom';

import { showActionToast } from '../../notifications/actionToastSlice';
import { selectFolderList } from './foldersSlice';
import { buildFolderTree, folderPath, type FolderTree } from './folderTree';
import type { Folder, FolderType } from './types';

/** The URL parameter that holds the open folder. */
export const FOLDER_PARAM = 'folder';

export type FolderParam = {
  /** The folder the URL opens, or null at the root. */
  folderId: string | null;
  /** That folder once the list has loaded it; null at the root or before. */
  folder: Folder | null;
  /** Its trail, top level first, the folder last; empty at the root. */
  trail: Folder[];
  tree: FolderTree;
  /** Open a folder (null: the root) as a new history entry. */
  openFolder: (folderId: string | null) => void;
};

/**
 * The open folder of a page, kept in the URL (`?folder=<id>`) so a link and
 * the browser's Back work. The trail comes from the folder list's parent
 * chain in Redux, so a link to a nested folder shows every parent. A folder
 * the list doesn't have (deleted, or someone else's) sends the page back to
 * the root with a toast.
 */
export function useFolderParam(type: FolderType): FolderParam {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const [searchParams, setSearchParams] = useSearchParams();
  const list = useSelector(selectFolderList(type));
  const tree = useMemo(() => buildFolderTree(list.items), [list.items]);
  const folderId = searchParams.get(FOLDER_PARAM) || null;

  const setFolder = useCallback(
    (id: string | null, replace = false) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (id) next.set(FOLDER_PARAM, id);
          else next.delete(FOLDER_PARAM);
          return next;
        },
        { replace },
      );
    },
    [setSearchParams],
  );

  const missing = Boolean(folderId) && list.loaded && !tree.byId.has(folderId!);
  const toasted = useRef<string | null>(null);
  useEffect(() => {
    if (!missing || !folderId) return;
    // Deleted here: its contents went to the parent, and so does the page.
    if (folderId in list.removedParents) {
      setFolder(list.removedParents[folderId], true);
      return;
    }
    if (toasted.current === folderId) return;
    toasted.current = folderId;
    dispatch(
      showActionToast({
        variant: 'destructive',
        message: t('folders.errors.openFailed'),
      }),
    );
    setFolder(null, true);
  }, [missing, folderId, list.removedParents, dispatch, setFolder, t]);

  const folder = folderId ? (tree.byId.get(folderId) ?? null) : null;
  const trail = useMemo(
    () => (folder ? folderPath(tree, folder.id) : []),
    [tree, folder],
  );

  const openFolder = useCallback(
    (id: string | null) => setFolder(id),
    [setFolder],
  );

  return { folderId, folder, trail, tree, openFolder };
}
