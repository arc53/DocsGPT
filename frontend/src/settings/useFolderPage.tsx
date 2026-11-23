import { type ReactNode, useState } from 'react';

import FolderNameModal from '../components/folders/FolderNameModal';
import type { FolderListState } from '../components/folders/foldersSlice';
import type { FolderTree } from '../components/folders/folderTree';
import type { Folder, ItemKind } from '../components/folders/types';
import {
  type FolderMenu,
  useFolderMenu,
} from '../components/folders/useFolderMenu';
import { useFolderParam } from '../components/folders/useFolderParam';
import { useFolderTree } from '../components/folders/useFolderTree';

export type FolderPage = {
  /** The folder the URL opens, or null at the root. */
  folderId: string | null;
  /** That folder once the tree has it. */
  folder: Folder | null;
  /** Its trail, top level first. */
  trail: Folder[];
  tree: FolderTree;
  /** The tree's folders and where its load stands. */
  list: FolderListState;
  /** Load the tree again (Retry after a failed load). */
  reload: () => void;
  openFolder: (folderId: string | null) => void;
  /** Each folder's ⋯ (Rename, Move to folder, Move to team…, Delete). */
  folderMenu: FolderMenu;
  /** Opens New folder at the level open here. */
  newFolder: () => void;
  /** The folder dialogs; render once. */
  dialogs: ReactNode;
};

/**
 * The folder side of a list page that files its items in the workspace's
 * one tree (Tools, Prompts): the tree, loaded once; the open folder from the
 * URL (`?folder=`); each folder's ⋯; and New folder at the open level.
 *
 * Args:
 *   kind: The page's kind.
 *   reloadItems: Loads the page's items again, after a folder's delete
 *     moved them to its parent or a move took them to another workspace.
 *
 * Returns:
 *   The open folder, the tree, the folder menu, `newFolder` and the
 *   `dialogs` to render.
 */
export function useFolderPage(
  kind: ItemKind,
  reloadItems: () => void,
): FolderPage {
  const { list, reload } = useFolderTree();
  const { folderId, folder, trail, tree, openFolder } = useFolderParam(kind);
  const folderMenu = useFolderMenu(kind, () => reloadItems(), {
    onMovedToWorkspace: reloadItems,
  });
  const [newFolderOpen, setNewFolderOpen] = useState(false);

  const dialogs = (
    <>
      {folderMenu.dialogs}
      <FolderNameModal
        open={newFolderOpen}
        onOpenChange={setNewFolderOpen}
        kind={kind}
        mode="create"
        parentId={folderId}
      />
    </>
  );

  return {
    folderId,
    folder,
    trail,
    tree,
    list,
    reload,
    openFolder,
    folderMenu,
    newFolder: () => setNewFolderOpen(true),
    dialogs,
  };
}
