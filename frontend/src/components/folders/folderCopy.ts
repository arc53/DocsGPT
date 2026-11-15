import type { TFunction } from 'i18next';

import { formatCount } from '../../utils/dateTimeUtils';
import { folderErrorCode } from './useFolderActions';
import { type Folder, ITEM_KINDS, type ItemKind } from './types';

type Counted = Pick<Folder, 'item_count' | 'folder_count' | 'counts'>;

/** "2 agents", "3 sources", "1 folder": a plural count of one kind. */
export const folderCount = (
  t: TFunction,
  kind: ItemKind | 'folder',
  count: number,
): string =>
  t(`folders.counts.${kind}`, { count, formatted: formatCount(count) });

/**
 * Items of one kind filed directly in a folder. A folder without `counts`
 * (an older server, which counted only the kind it was asked for) reads its
 * `item_count`.
 */
export const folderKindCount = (folder: Counted, kind: ItemKind): number =>
  folder.counts ? (folder.counts[kind] ?? 0) : (folder.item_count ?? 0);

/**
 * The other kinds a folder holds directly, in the tree's kind order, for
 * "also 2 agents, 3 tools" and the links to their pages.
 *
 * Args:
 *   folder: The folder.
 *   kind: The page's kind, left out.
 *
 * Returns:
 *   Each other kind with a count above zero.
 */
export function folderOtherKinds(
  folder: Counted,
  kind: ItemKind,
): { kind: ItemKind; count: number }[] {
  if (!folder.counts) return [];
  return ITEM_KINDS.filter((other) => other !== kind)
    .map((other) => ({ kind: other, count: folder.counts?.[other] ?? 0 }))
    .filter((entry) => entry.count > 0);
}

/** Items joined for a list in running text: "2 agents, 3 tools". */
export const folderListJoin = (t: TFunction, parts: string[]): string =>
  parts.join(t('folders.listSeparator'));

/**
 * A folder's line two on a page of one kind: "6 prompts · also 2 agents, 3
 * tools", "3 sources · 1 folder", "2 agents", or "Empty". With nothing of the
 * page's kind and no folders inside, the other kinds stand alone ("1
 * agent"). Counted on the server (direct children the caller can see), so a
 * search doesn't change it.
 *
 * Args:
 *   t: The translator.
 *   folder: The folder.
 *   kind: The page's kind, counted first.
 *   options.also: Name the other kinds (default true); a picker of one kind
 *     leaves them out.
 */
export function folderCountLine(
  t: TFunction,
  folder: Counted,
  kind: ItemKind,
  { also = true }: { also?: boolean } = {},
): string {
  const items = folderKindCount(folder, kind);
  const folders = folder.folder_count ?? 0;
  const parts = [
    items > 0 ? folderCount(t, kind, items) : null,
    folders > 0 ? folderCount(t, 'folder', folders) : null,
  ].filter((part): part is string => part !== null);
  const others = also
    ? folderOtherKinds(folder, kind).map((entry) =>
        folderCount(t, entry.kind, entry.count),
      )
    : [];
  if (others.length > 0) {
    const list = folderListJoin(t, others);
    parts.push(
      parts.length > 0
        ? t('folders.counts.also', {
            list,
            interpolation: { escapeValue: false },
          })
        : list,
    );
  }
  return parts.length > 0 ? parts.join(' · ') : t('folders.counts.empty');
}

/**
 * The root of a page's folders: "My agents", "Knowledge", "Tools",
 * "Prompts". In a team the agents are the team's, so its root is "Agents".
 */
export const folderRootLabel = (
  t: TFunction,
  kind: ItemKind,
  { team = false }: { team?: boolean } = {},
): string =>
  t(
    kind === 'agent' && team
      ? 'folders.root.teamAgent'
      : `folders.root.${kind}`,
  );

/**
 * What a delete does to the folder's contents, for the confirm's description:
 * "Its 6 prompts, 2 agents and 1 folder move to Prompts. Nothing is deleted."
 * The page's kind comes first, then every other kind, then the folders.
 */
export function folderDeleteConsequence(
  t: TFunction,
  folder: Counted,
  kind: ItemKind,
  parentLabel: string,
): string {
  const items = folderKindCount(folder, kind);
  const others = folderOtherKinds(folder, kind);
  const folders = folder.folder_count ?? 0;
  const total =
    items + others.reduce((sum, entry) => sum + entry.count, 0) + folders;
  if (total === 0) return t('folders.deleteEmpty');
  const parts = [
    items > 0 ? folderCount(t, kind, items) : null,
    ...others.map((entry) => folderCount(t, entry.kind, entry.count)),
    folders > 0 ? folderCount(t, 'folder', folders) : null,
  ].filter((part): part is string => part !== null);
  const what =
    parts.length >= 2
      ? t('folders.and', {
          first: folderListJoin(t, parts.slice(0, -1)),
          second: parts[parts.length - 1],
          interpolation: { escapeValue: false },
        })
      : parts[0];
  return t('folders.deleteMoves', {
    count: total,
    what,
    parent: parentLabel,
    interpolation: { escapeValue: false },
  });
}

/** A child folder a delete renamed so names stay unique where it landed. */
export type RenamedFolder = { id: string; from: string; to: string };

/**
 * The toast after a delete that renamed folders: "Folder deleted. 2 folders
 * were renamed to keep names unique: Rates → Rates (2), …". Null when none
 * was renamed (the folder leaving the page says enough).
 */
export function folderRenamedMessage(
  t: TFunction,
  renamed: RenamedFolder[] | undefined,
): string | null {
  if (!renamed || renamed.length === 0) return null;
  const list = folderListJoin(
    t,
    renamed.map((entry) => `${entry.from} → ${entry.to}`),
  );
  return t('folders.deletedRenamed', {
    count: renamed.length,
    formatted: formatCount(renamed.length),
    list,
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
  // The UI offers neither move; a stale page can still send one.
  team_item_not_fileable: 'folders.errors.teamItemNotFileable',
  item_not_in_team: 'folders.errors.itemNotInTeam',
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
