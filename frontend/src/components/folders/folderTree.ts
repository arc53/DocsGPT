import { type Folder, MAX_FOLDER_DEPTH } from './types';

/**
 * The folder list as a tree. The server keeps folders acyclic and three
 * levels deep, but an older row can break either rule, so every walk here is
 * cycle-safe: a folder whose parent chain loops, or whose parent is missing,
 * counts as a top-level folder.
 */
export type FolderTree = {
  byId: Map<string, Folder>;
  /** The parent each folder is shown under (null: the top level). */
  parentOf: Map<string, string | null>;
  /** Children by parent id (null: the top level), sorted by name. */
  children: Map<string | null, Folder[]>;
};

const collator = new Intl.Collator(undefined, {
  sensitivity: 'base',
  numeric: true,
});

/** Folders by name, as people expect a folder list (Finder, Drive). */
export const sortFoldersByName = (folders: Folder[]): Folder[] =>
  [...folders].sort((a, b) => collator.compare(a.name, b.name));

/**
 * Builds the tree from the flat list `GET /api/folders` returns.
 *
 * Args:
 *   folders: The caller's folders of one type.
 *
 * Returns:
 *   The tree: folders by id, each one's parent, and children by parent.
 */
export function buildFolderTree(folders: Folder[]): FolderTree {
  const byId = new Map(folders.map((folder) => [folder.id, folder]));
  const parentOf = new Map<string, string | null>();
  for (const folder of folders) {
    let parent = folder.parent_id ?? null;
    if (parent !== null && !byId.has(parent)) parent = null;
    // Walk up from the parent; meeting this folder again is a loop. A chain
    // that runs into some other loop stops there, and that loop's members
    // become top-level folders themselves.
    const seen = new Set<string>();
    let cursor = parent;
    while (cursor !== null && !seen.has(cursor)) {
      if (cursor === folder.id) {
        parent = null;
        break;
      }
      seen.add(cursor);
      const next = byId.get(cursor)?.parent_id ?? null;
      cursor = next !== null && byId.has(next) ? next : null;
    }
    parentOf.set(folder.id, parent);
  }
  const children = new Map<string | null, Folder[]>();
  for (const folder of folders) {
    const parent = parentOf.get(folder.id) ?? null;
    children.set(parent, [...(children.get(parent) ?? []), folder]);
  }
  for (const [key, list] of children)
    children.set(key, sortFoldersByName(list));
  return { byId, parentOf, children };
}

/** The folders directly inside `parentId` (null: the top level). */
export const childFolders = (
  tree: FolderTree,
  parentId: string | null,
): Folder[] => tree.children.get(parentId) ?? [];

/**
 * The trail to a folder, top level first, the folder itself last. Empty for
 * an id the tree doesn't hold.
 */
export function folderPath(tree: FolderTree, id: string | null): Folder[] {
  const path: Folder[] = [];
  const seen = new Set<string>();
  let cursor = id;
  while (cursor !== null && !seen.has(cursor)) {
    const folder = tree.byId.get(cursor);
    if (!folder) break;
    seen.add(cursor);
    path.unshift(folder);
    cursor = tree.parentOf.get(cursor) ?? null;
  }
  return path;
}

/** How deep a folder sits: 1 at the top level, 0 for the root (null). */
export const folderDepth = (tree: FolderTree, id: string | null): number =>
  folderPath(tree, id).length;

/** The folder and every folder under it. */
export function subtreeIds(tree: FolderTree, id: string): Set<string> {
  const ids = new Set<string>();
  const stack = [id];
  while (stack.length > 0) {
    const current = stack.pop() as string;
    if (ids.has(current)) continue;
    ids.add(current);
    for (const child of childFolders(tree, current)) stack.push(child.id);
  }
  return ids;
}

/** How many levels a folder spans with its subfolders: 1 for a leaf. */
export function subtreeHeight(tree: FolderTree, id: string): number {
  const height = (current: string, seen: Set<string>): number => {
    if (seen.has(current)) return 0;
    const next = new Set(seen).add(current);
    const kids = childFolders(tree, current);
    return 1 + Math.max(0, ...kids.map((kid) => height(kid.id, next)));
  };
  return height(id, new Set());
}

/** Whether a new folder may go inside `parentId` (null: the top level). */
export const canCreateIn = (
  tree: FolderTree,
  parentId: string | null,
): boolean => folderDepth(tree, parentId) < MAX_FOLDER_DEPTH;

/**
 * Whether a folder may move under `targetParentId`: `same` when it is
 * already there, `cycle` into itself or a folder inside it, `too_deep` when
 * its deepest subfolder would pass the depth limit.
 */
export function folderMoveCheck(
  tree: FolderTree,
  folderId: string,
  targetParentId: string | null,
): 'ok' | 'same' | 'cycle' | 'too_deep' {
  if ((tree.parentOf.get(folderId) ?? null) === targetParentId) return 'same';
  if (targetParentId !== null && subtreeIds(tree, folderId).has(targetParentId))
    return 'cycle';
  const depth =
    folderDepth(tree, targetParentId) + subtreeHeight(tree, folderId);
  return depth > MAX_FOLDER_DEPTH ? 'too_deep' : 'ok';
}

/** A trail as one line: "Carriers › Rate archive". */
export const formatFolderPath = (path: Folder[]): string =>
  path.map((folder) => folder.name).join(' › ');
