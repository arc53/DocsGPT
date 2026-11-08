import type { Doc } from '../../models/misc';
import { sourceItemId } from '../../utils/sourceUtils';
import { type FolderTree, folderPath, subtreeIds } from './folderTree';
import type { Folder } from './types';

/**
 * What a knowledge picker holds: single sources (by picker id, see
 * `sourceItemId`) and whole folders (by id). A picked folder is live: the
 * server reads what is filed in it, subfolders included, on every answer.
 */
export type KnowledgePick = { sources: string[]; folders: string[] };

export const EMPTY_PICK: KnowledgePick = { sources: [], folders: [] };

const FOLDER_ROW_PREFIX = 'folder:';

/** A folder's row id in a picker list, apart from source ids. */
export const folderRowId = (folderId: string): string =>
  `${FOLDER_ROW_PREFIX}${folderId}`;

/** The folder a picker row stands for, or null for a source row. */
export const folderIdOfRow = (rowId: string): string | null =>
  rowId.startsWith(FOLDER_ROW_PREFIX)
    ? rowId.slice(FOLDER_ROW_PREFIX.length)
    : null;

/** The picker's selected row ids: the sources, then each folder's row id. */
export const pickRowIds = (pick: KnowledgePick): string[] => [
  ...pick.sources,
  ...pick.folders.map(folderRowId),
];

/**
 * The folder a source is filed in, when the tree knows it; a source filed in
 * a folder the list doesn't hold counts as in none.
 */
export const docFolderId = (tree: FolderTree, doc: Doc): string | null =>
  doc.folder_id && tree.byId.has(doc.folder_id) ? doc.folder_id : null;

/**
 * The picked folder that brings in `folderId`: the outermost picked folder
 * on its trail, itself included. Null when none is picked.
 */
export function coveringFolder(
  tree: FolderTree,
  folderId: string | null,
  picked: ReadonlySet<string>,
): Folder | null {
  if (folderId === null) return null;
  return folderPath(tree, folderId).find((f) => picked.has(f.id)) ?? null;
}

/**
 * The picked folder a source comes in with, so it can't be picked on its own.
 */
export const sourceIncludedBy = (
  tree: FolderTree,
  doc: Doc,
  pick: KnowledgePick,
): Folder | null =>
  coveringFolder(tree, docFolderId(tree, doc), new Set(pick.folders));

export type FolderPickState = {
  /** The tri-state checkbox: none, some ("1 of 2 picked") or all. */
  state: 'none' | 'some' | 'all';
  /** A picked folder above this one that already brings it in. */
  includedBy: Folder | null;
  /** The sources in the folder's subtree that are in the pick. */
  picked: number;
  /** Every source in the folder's subtree. */
  total: number;
};

/**
 * How much of a folder is picked. `all` when the folder or a folder above it
 * is picked; `some` when a source or a subfolder inside it is; else `none`.
 *
 * Args:
 *   tree: The source folder tree.
 *   docs: Every source the picker lists.
 *   pick: The current pick.
 *   folderId: The folder.
 *
 * Returns:
 *   The state, the folder above that includes it, and the picked and total
 *   source counts across its subtree.
 */
export function folderPickState(
  tree: FolderTree,
  docs: Doc[],
  pick: KnowledgePick,
  folderId: string,
): FolderPickState {
  const pickedFolders = new Set(pick.folders);
  const trail = folderPath(tree, folderId);
  const includedBy =
    trail.slice(0, -1).find((f) => pickedFolders.has(f.id)) ?? null;
  const subtree = subtreeIds(tree, folderId);
  const pickedSources = new Set(pick.sources);
  let picked = 0;
  let total = 0;
  for (const doc of docs) {
    const home = docFolderId(tree, doc);
    if (home === null || !subtree.has(home)) continue;
    total += 1;
    if (
      pickedSources.has(sourceItemId(doc)) ||
      coveringFolder(tree, home, pickedFolders) !== null
    )
      picked += 1;
  }
  if (pickedFolders.has(folderId) || includedBy)
    return { state: 'all', includedBy, picked: total, total };
  const subfolderPicked = [...subtree].some((id) => pickedFolders.has(id));
  return {
    state: picked > 0 || subfolderPicked ? 'some' : 'none',
    includedBy: null,
    picked,
    total,
  };
}

/**
 * The pick after a row is clicked. A folder toggles as one item; picking it
 * replaces what was picked inside it (its sources and subfolders), since the
 * folder now brings them all. A row a picked folder already brings in can't
 * change, so its click leaves the pick as it was.
 *
 * Args:
 *   tree: The source folder tree.
 *   docs: Every source the picker lists.
 *   pick: The current pick.
 *   rowId: The clicked row: a source id or a `folderRowId`.
 *
 * Returns:
 *   The new pick (the same object when nothing changed).
 */
export function togglePick(
  tree: FolderTree,
  docs: Doc[],
  pick: KnowledgePick,
  rowId: string,
): KnowledgePick {
  const folderId = folderIdOfRow(rowId);
  const pickedFolders = new Set(pick.folders);
  if (folderId === null) {
    if (pick.sources.includes(rowId))
      return { ...pick, sources: pick.sources.filter((id) => id !== rowId) };
    const doc = docs.find((item) => sourceItemId(item) === rowId);
    if (doc && sourceIncludedBy(tree, doc, pick)) return pick;
    return { ...pick, sources: [...pick.sources, rowId] };
  }
  if (pickedFolders.has(folderId))
    return { ...pick, folders: pick.folders.filter((id) => id !== folderId) };
  if (folderPickState(tree, docs, pick, folderId).includedBy) return pick;
  const subtree = subtreeIds(tree, folderId);
  const inside = new Set(
    docs
      .filter((doc) => {
        const home = docFolderId(tree, doc);
        return home !== null && subtree.has(home);
      })
      .map((doc) => sourceItemId(doc)),
  );
  return {
    sources: pick.sources.filter((id) => !inside.has(id)),
    folders: [...pick.folders.filter((id) => !subtree.has(id)), folderId],
  };
}
