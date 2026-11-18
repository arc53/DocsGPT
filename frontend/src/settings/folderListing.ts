import {
  childFolders,
  folderPath,
  folderShowsOn,
  formatFolderPath,
  matchingFolders,
  subtreeIds,
  type FolderTree,
} from '../components/folders/folderTree';
import type { Folder, ItemKind } from '../components/folders/types';

/** An item's filing in the workspace's tree, as tools and prompts carry it. */
export type FiledItem = { folder_id?: string | null };

/**
 * Whether an item sits right at a level of the page: in the open folder, or
 * at the root when it is in no folder (or one the tree doesn't know).
 *
 * Args:
 *   tree: The workspace's folder tree.
 *   item: The item.
 *   folderId: The open folder, or null at the root.
 *
 * Returns:
 *   True when the level lists it.
 */
export function filedAt(
  tree: FolderTree,
  item: FiledItem,
  folderId: string | null,
): boolean {
  const id = item.folder_id ?? null;
  if (folderId === null) return id === null || !tree.byId.has(id);
  return id === folderId;
}

/**
 * The items a search or a filter lists: every item at the root, or those in
 * the open folder and the folders under it.
 *
 * Args:
 *   tree: The workspace's folder tree.
 *   items: The page's items.
 *   folderId: The open folder, or null at the root.
 *
 * Returns:
 *   The items in reach, in their order.
 */
export function itemsWithin<T extends FiledItem>(
  tree: FolderTree,
  items: T[],
  folderId: string | null,
): T[] {
  if (folderId === null) return items;
  const subtree = subtreeIds(tree, folderId);
  return items.filter(
    (item) => !!item.folder_id && subtree.has(item.folder_id),
  );
}

/**
 * The folder tiles a page of one kind shows at a level: the folders right
 * here, or for a search the matching ones from every level below, either
 * way only those that hold the page's kind or nothing at all.
 *
 * Args:
 *   tree: The workspace's folder tree.
 *   kind: The page's kind.
 *   folderId: The open folder, or null at the root.
 *   query: The search; blank lists the level's own folders.
 *
 * Returns:
 *   The folders to show.
 */
export function listedFolders(
  tree: FolderTree,
  kind: ItemKind,
  folderId: string | null,
  query: string,
): Folder[] {
  const folders = query.trim()
    ? matchingFolders(
        tree,
        query,
        folderId === null
          ? undefined
          : new Set(
              [...subtreeIds(tree, folderId)].filter((id) => id !== folderId),
            ),
      )
    : childFolders(tree, folderId);
  return folders.filter((folder) => folderShowsOn(tree, folder, kind));
}

/**
 * Where an item a search or filter found is filed, for its tile: the trail
 * below the open folder ("Customer-facing › EU"); nothing for an item in no
 * folder or right in the open one.
 *
 * Args:
 *   tree: The workspace's folder tree.
 *   item: The item.
 *   openId: The open folder, or null at the root.
 *
 * Returns:
 *   The trail, or undefined.
 */
export function folderLabelOf(
  tree: FolderTree,
  item: FiledItem,
  openId: string | null,
): string | undefined {
  const id = item.folder_id ?? null;
  if (id === null || id === openId || !tree.byId.has(id)) return undefined;
  const path = folderPath(tree, id);
  const start = openId ? path.findIndex((f) => f.id === openId) + 1 : 0;
  return formatFolderPath(path.slice(start));
}
