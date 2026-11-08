import type { TFunction } from 'i18next';

import type { Doc } from '../../models/misc';
import { formatCount, intlLocale } from '../../utils/dateTimeUtils';
import { docFolderId } from './folderPick';
import { type FolderTree, subtreeIds } from './folderTree';

/**
 * A folder on an agent or a workflow step as the server describes it
 * (`folder_details`, `ref_details.folders`).
 */
export type FolderRefDetail = {
  id: string;
  /** Null once the folder was deleted. */
  name: string | null;
  /** The sources it feeds now. */
  source_count?: number;
  /** Its owner, when that isn't the reader. */
  owner_name?: string;
  stopped?: boolean;
  reason?: 'sponsor_cannot_edit_agent' | 'deleted' | string;
};

/** A picked folder, named and counted for the reader. */
export type PickedFolder = {
  id: string;
  name: string | null;
  /** The sources it brings today. */
  sourceCount: number;
  /** Its owner when someone else filed it (a teammate's folder). */
  ownerName?: string;
  /** Why it brings nothing now, if so. */
  stopped?: 'sponsor_cannot_edit_agent' | 'deleted';
};

/**
 * The picked folders, named and counted: from the reader's own folder tree
 * (counted live, so a pick shows at once), else from the server's details (a
 * teammate's folder, or a deleted one).
 *
 * Args:
 *   tree: The reader's source folders.
 *   docs: The sources the reader lists.
 *   ids: The picked folder ids, in order.
 *   details: The server's details for the folders on the agent or step.
 *
 * Returns:
 *   One entry per picked folder.
 */
export function pickedFolders(
  tree: FolderTree,
  docs: Doc[],
  ids: string[],
  details: FolderRefDetail[] = [],
): PickedFolder[] {
  return ids.map((id) => {
    const detail = details.find((item) => item.id === id);
    const stopped =
      detail?.reason === 'deleted' || (detail && detail.name === null)
        ? 'deleted'
        : detail?.stopped && detail.reason === 'sponsor_cannot_edit_agent'
          ? 'sponsor_cannot_edit_agent'
          : undefined;
    const own = tree.byId.get(id);
    if (own) {
      const subtree = subtreeIds(tree, id);
      const sourceCount = docs.filter((doc) => {
        const home = docFolderId(tree, doc);
        return home !== null && subtree.has(home);
      }).length;
      return { id, name: own.name, sourceCount };
    }
    return {
      id,
      name: detail?.name ?? null,
      sourceCount: detail?.source_count ?? 0,
      ownerName: detail?.owner_name,
      stopped: stopped ?? (detail ? undefined : 'deleted'),
    };
  });
}

const listNames = (names: string[], language?: string) =>
  new Intl.ListFormat(intlLocale(language), { type: 'conjunction' }).format(
    names,
  );

/**
 * What the picked folders bring, under the knowledge field: "Carriers is a
 * folder: its 7 sources today, and any added to it later." Null with no
 * running folder.
 */
export function pickedFoldersHint(
  t: TFunction,
  folders: PickedFolder[],
  language?: string,
): string | null {
  const live = folders.filter((folder) => !folder.stopped && folder.name);
  if (live.length === 0) return null;
  const count = live.reduce((sum, folder) => sum + folder.sourceCount, 0);
  const options = {
    count,
    formatted: formatCount(count),
    interpolation: { escapeValue: false },
  };
  return live.length === 1
    ? t('folders.picker.hintOne', { ...options, name: live[0].name })
    : t('folders.picker.hintMany', {
        ...options,
        names: listNames(
          live.map((folder) => folder.name as string),
          language,
        ),
      });
}

/** Why each stopped folder brings nothing, one line each. */
export function stoppedFolderLines(
  t: TFunction,
  folders: PickedFolder[],
): string[] {
  const lines = folders
    .filter((folder) => folder.stopped === 'sponsor_cannot_edit_agent')
    .map((folder) =>
      folder.ownerName
        ? t('folders.picker.stopped', {
            name: folder.name,
            person: folder.ownerName,
            interpolation: { escapeValue: false },
          })
        : t('folders.picker.stoppedOther', {
            name: folder.name,
            interpolation: { escapeValue: false },
          }),
    );
  const deleted = folders.filter((folder) => folder.stopped === 'deleted');
  if (deleted.length > 0)
    lines.push(
      t('folders.picker.deleted', {
        count: deleted.length,
        formatted: formatCount(deleted.length),
      }),
    );
  return lines;
}

/** A picked folder's name, or "Deleted folder". */
export const pickedFolderLabel = (t: TFunction, folder: PickedFolder): string =>
  folder.name ?? t('folders.picker.deletedFolder');

/**
 * The row of a picked folder the reader's tree doesn't hold, in the picker:
 * its name and whose it is, or that it was deleted, so it can be taken off.
 */
export function unlistedFolderRow(
  t: TFunction,
  folder: PickedFolder,
): { label: string; line?: string } {
  const label = pickedFolderLabel(t, folder);
  if (folder.stopped === 'deleted')
    return { label, line: t('folders.picker.deletedLine') };
  const parts = [
    folder.ownerName
      ? t('folders.picker.ownersFolder', {
          person: folder.ownerName,
          interpolation: { escapeValue: false },
        })
      : null,
    folder.stopped
      ? t('folders.picker.stoppedShort')
      : t('folders.counts.source', {
          count: folder.sourceCount,
          formatted: formatCount(folder.sourceCount),
        }),
  ];
  return { label, line: parts.filter(Boolean).join(' · ') };
}
