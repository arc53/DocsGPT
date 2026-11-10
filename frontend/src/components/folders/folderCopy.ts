import type { TFunction } from 'i18next';

import { formatCount } from '../../utils/dateTimeUtils';
import { folderErrorCode } from './useFolderActions';
import type { Folder, FolderType } from './types';

/** "2 agents", "3 sources", "1 folder": a plural count of one kind. */
export const folderCount = (
  t: TFunction,
  kind: FolderType | 'folder',
  count: number,
): string =>
  t(`folders.counts.${kind}`, { count, formatted: formatCount(count) });

/**
 * A folder's line two: "3 sources · 1 folder", "2 agents", or "Empty".
 * Counted on the server (direct children the caller can see), so a search
 * doesn't change it.
 */
export function folderCountLine(
  t: TFunction,
  folder: Pick<Folder, 'item_count' | 'folder_count'>,
  type: FolderType,
): string {
  const items = folder.item_count ?? 0;
  const folders = folder.folder_count ?? 0;
  const parts = [
    items > 0 ? folderCount(t, type, items) : null,
    folders > 0 ? folderCount(t, 'folder', folders) : null,
  ].filter((part): part is string => part !== null);
  return parts.length > 0 ? parts.join(' · ') : t('folders.counts.empty');
}

/** The root of a type's folders: "My agents" or "Knowledge". */
export const folderRootLabel = (t: TFunction, type: FolderType): string =>
  t(`folders.root.${type}`);

/**
 * What a delete does to the folder's contents, for the confirm's description:
 * "Its 12 sources and 2 folders move to Knowledge. Nothing is deleted."
 */
export function folderDeleteConsequence(
  t: TFunction,
  folder: Pick<Folder, 'item_count' | 'folder_count'>,
  type: FolderType,
  parentLabel: string,
): string {
  const items = folder.item_count ?? 0;
  const folders = folder.folder_count ?? 0;
  if (items + folders === 0) return t('folders.deleteEmpty');
  const parts = [
    items > 0 ? folderCount(t, type, items) : null,
    folders > 0 ? folderCount(t, 'folder', folders) : null,
  ].filter((part): part is string => part !== null);
  const what =
    parts.length === 2
      ? t('folders.and', { first: parts[0], second: parts[1] })
      : parts[0];
  return t('folders.deleteMoves', {
    count: items + folders,
    what,
    parent: parentLabel,
    interpolation: { escapeValue: false },
  });
}

const ERROR_KEYS: Record<string, string> = {
  folder_name_taken: 'folders.errors.nameTaken',
  folder_too_deep: 'folders.errors.tooDeep',
  folder_cycle: 'folders.errors.cycle',
  invalid_folder_name: 'folders.errors.invalidName',
  folder_not_found: 'folders.errors.notFound',
  skipped: 'folders.errors.cantFile',
};

/**
 * The message for a refused folder request, by its code; `fallbackKey` for
 * anything else (a transport failure, a 500).
 */
export const folderErrorMessage = (
  t: TFunction,
  reason: unknown,
  fallbackKey: string,
): string => t(ERROR_KEYS[folderErrorCode(reason)] ?? fallbackKey);
