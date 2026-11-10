import type { TFunction } from 'i18next';
import { Folder as FolderIcon } from 'lucide-react';

import type { Doc } from '../../models/misc';
import { sourceItemId } from '../../utils/sourceUtils';
import type { MultiSelectPopoverItem } from '../MultiSelectPopover';
import { folderCount, folderCountLine } from './folderCopy';
import {
  docFolderId,
  folderPickState,
  folderRowId,
  sourceIncludedBy,
  type KnowledgePick,
} from './folderPick';
import {
  childFolders,
  type FolderTree,
  folderPath,
  formatFolderPath,
  matchingFolders,
  subtreeIds,
} from './folderTree';
import type { Folder } from './types';

/** A picked folder the caller's tree doesn't hold: deleted, or a teammate's. */
export type UnlistedFolderRow = { id: string; label: string; line?: string };

export type KnowledgeRowsInput = {
  t: TFunction;
  tree: FolderTree;
  /** Every source the picker lists (the counts read these). */
  docs: Doc[];
  /** The sources the kind track lets through, within the open place. */
  shownDocs: Doc[];
  pick: KnowledgePick;
  /** The open folder, or null at the root. */
  place: string | null;
  /** The search as typed. */
  query: string;
  /** A kind other than All is picked on the track. */
  kindFiltered: boolean;
  /**
   * A source's row: its icon, its line (led by `linePrefix` when given) and
   * its badges, as `toSourcePickerItems` draws it.
   */
  sourceRow: (doc: Doc, linePrefix: string | null) => MultiSelectPopoverItem;
  /** Rows for picked sources the reader can't list (remove-only). */
  extraSources?: MultiSelectPopoverItem[];
  /** Rows for picked folders the tree doesn't hold (remove-only). */
  unlistedFolders?: UnlistedFolderRow[];
  /** Open a folder (its chevron). */
  onOpen: (folderId: string) => void;
};

/** Rows from a search: the caller filters, by name and line, any case. */
const matchesQuery = (item: MultiSelectPopoverItem, needle: string) =>
  [item.label, item.description, ...(item.keywords ?? [])]
    .filter(Boolean)
    .some((text) => (text as string).toLowerCase().includes(needle));

/**
 * The rows of a knowledge picker that knows folders.
 *
 * - **Root**: Selected (what was picked as it opened, `selectedFirst`), then
 *   Folders (the top level, each with a tri-state box and a chevron that
 *   opens it), Sources (in no folder) and Shared with team. A picked source
 *   or subfolder filed deeper is listed only in Selected (`pinnedOnly`).
 * - **In a folder**: "All of <folder>" on top, then In this folder: its
 *   folders, then its sources. Inside a picked folder every row is checked,
 *   muted and fixed, "Included with <folder>".
 * - **Search or a kind filter**: flat over the place, folders whose name
 *   matches first (no chevron), then sources, each line led by its folder
 *   trail (below the open folder); an included row keeps its trail, its
 *   muted box saying it comes with a picked folder.
 *
 * Args:
 *   input: The tree, the sources, the pick, where the picker is and how
 *     to draw a source row.
 *
 * Returns:
 *   The picker rows, in order.
 */
export function buildKnowledgeRows({
  t,
  tree,
  docs,
  shownDocs,
  pick,
  place,
  query,
  kindFiltered,
  sourceRow,
  extraSources = [],
  unlistedFolders = [],
  onOpen,
}: KnowledgeRowsInput): MultiSelectPopoverItem[] {
  const labels = {
    folders: t('settings.sources.sections.folders'),
    own: t('settings.sources.sections.sources'),
    team: t('conversation.sources.groupTeam'),
    inFolder: t('folders.picker.inFolder'),
  };
  const needle = query.trim().toLowerCase();
  const flat = needle !== '' || kindFiltered;
  const placeFolder = place ? (tree.byId.get(place) ?? null) : null;
  const pickedSources = new Set(pick.sources);

  /** The trail of folders a folder sits in, below the open place. */
  const trailBelowPlace = (folderId: string | null): string | null => {
    if (folderId === null) return null;
    const path = folderPath(tree, folderId);
    const start = place ? path.findIndex((f) => f.id === place) + 1 : 0;
    const below = path.slice(start);
    return below.length > 0 ? formatFolderPath(below) : null;
  };
  const includedLine = (folder: Folder) =>
    t('folders.picker.includedWith', {
      name: folder.name,
      interpolation: { escapeValue: false },
    });

  const folderRow = (
    folder: Folder,
    {
      group,
      opener,
      lead = null,
      pinnedOnly = false,
    }: {
      group: string;
      opener: boolean;
      lead?: string | null;
      pinnedOnly?: boolean;
    },
  ): MultiSelectPopoverItem => {
    const state = folderPickState(tree, docs, pick, folder.id);
    const countLine = folderCountLine(t, folder, 'source');
    // A flat list leads with the trail, which already names the folder
    // that brings it in; the muted box says it is included.
    const stateLine = state.includedBy
      ? flat
        ? countLine
        : `${includedLine(state.includedBy)} · ${countLine}`
      : state.state === 'all'
        ? t('folders.picker.live', {
            what: folderCount(t, 'source', state.total),
          })
        : state.state === 'some' && state.picked > 0
          ? t('folders.picker.partial', {
              picked: state.picked,
              total: state.total,
            })
          : countLine;
    return {
      id: folderRowId(folder.id),
      label: folder.name,
      icon: <FolderIcon className="text-muted-foreground size-5" />,
      description: [lead, stateLine].filter(Boolean).join(' · '),
      group,
      checked: state.includedBy
        ? true
        : state.state === 'some'
          ? 'indeterminate'
          : undefined,
      muted: Boolean(state.includedBy),
      disabled: Boolean(state.includedBy),
      onOpen: opener ? () => onOpen(folder.id) : undefined,
      openLabel: opener
        ? t('folders.openFolder', {
            name: folder.name,
            interpolation: { escapeValue: false },
          })
        : undefined,
      pinnedOnly,
    };
  };

  const docRow = (
    doc: Doc,
    group: string,
    lead: string | null,
    pinnedOnly = false,
  ): MultiSelectPopoverItem => {
    const cover = sourceIncludedBy(tree, doc, pick);
    // In a folder, a source a picked folder brings in reads "Included with
    // <folder>"; a flat list keeps its trail, which names that folder.
    const row = sourceRow(doc, cover && !flat ? includedLine(cover) : lead);
    return {
      ...row,
      group,
      checked: cover ? true : undefined,
      muted: Boolean(cover),
      disabled: Boolean(cover) || row.disabled,
      pinnedOnly,
    };
  };
  const groupOf = (doc: Doc) =>
    doc.ownership === 'team' ? labels.team : labels.own;
  const unlistedRows = (): MultiSelectPopoverItem[] =>
    unlistedFolders.map((folder) => ({
      id: folderRowId(folder.id),
      label: folder.label,
      icon: <FolderIcon className="text-muted-foreground size-5" />,
      description: folder.line,
      group: labels.folders,
    }));

  if (flat) {
    const within = place
      ? new Set([...subtreeIds(tree, place)].filter((id) => id !== place))
      : undefined;
    const folders = needle
      ? matchingFolders(tree, needle, within).map((folder) =>
          folderRow(folder, {
            group: labels.folders,
            opener: false,
            lead: trailBelowPlace(tree.parentOf.get(folder.id) ?? null),
          }),
        )
      : [];
    const sources = shownDocs.map((doc) =>
      docRow(doc, groupOf(doc), trailBelowPlace(docFolderId(tree, doc))),
    );
    const extras = place
      ? []
      : [
          ...(needle ? unlistedRows() : []),
          ...extraSources.map((item) => ({ ...item, group: labels.own })),
        ];
    const rows = [...folders, ...sources, ...extras];
    return needle ? rows.filter((row) => matchesQuery(row, needle)) : rows;
  }

  if (placeFolder) {
    const state = folderPickState(tree, docs, pick, placeFolder.id);
    const all = folderRow(placeFolder, { group: '', opener: false });
    const allRow: MultiSelectPopoverItem = {
      ...all,
      label: t('folders.picker.allOf', {
        name: placeFolder.name,
        interpolation: { escapeValue: false },
      }),
      // The whole folder: its subtree's sources, not the direct count.
      description: state.includedBy
        ? `${includedLine(state.includedBy)} · ${folderCount(t, 'source', state.total)}`
        : state.state === 'none'
          ? folderCount(t, 'source', state.total)
          : all.description,
    };
    const inside = shownDocs.filter(
      (doc) => docFolderId(tree, doc) === placeFolder.id,
    );
    return [
      allRow,
      ...childFolders(tree, placeFolder.id).map((folder) =>
        folderRow(folder, { group: labels.inFolder, opener: true }),
      ),
      ...inside
        .filter((doc) => doc.ownership !== 'team')
        .map((doc) => docRow(doc, labels.inFolder, null)),
      ...inside
        .filter((doc) => doc.ownership === 'team')
        .map((doc) => docRow(doc, labels.inFolder, null)),
    ];
  }

  // The root.
  const topLevel = childFolders(tree, null);
  const topIds = new Set(topLevel.map((folder) => folder.id));
  const nestedPicked = pick.folders
    .filter((id) => tree.byId.has(id) && !topIds.has(id))
    .map((id) => tree.byId.get(id) as Folder);
  const loose = shownDocs.filter((doc) => docFolderId(tree, doc) === null);
  const filedPicked = shownDocs.filter(
    (doc) =>
      docFolderId(tree, doc) !== null && pickedSources.has(sourceItemId(doc)),
  );
  return [
    ...topLevel.map((folder) =>
      folderRow(folder, { group: labels.folders, opener: true }),
    ),
    ...nestedPicked.map((folder) =>
      folderRow(folder, {
        group: labels.folders,
        opener: true,
        lead: trailBelowPlace(tree.parentOf.get(folder.id) ?? null),
        pinnedOnly: true,
      }),
    ),
    ...unlistedRows(),
    ...loose
      .filter((doc) => doc.ownership !== 'team')
      .map((doc) => docRow(doc, labels.own, null)),
    ...extraSources.map((item) => ({ ...item, group: labels.own })),
    ...filedPicked.map((doc) =>
      docRow(doc, groupOf(doc), trailBelowPlace(docFolderId(tree, doc)), true),
    ),
    ...loose
      .filter((doc) => doc.ownership === 'team')
      .map((doc) => docRow(doc, labels.team, null)),
  ];
}
