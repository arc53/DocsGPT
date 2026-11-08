import { ChevronLeft } from 'lucide-react';
import { Fragment, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import type { Connection } from '../../connectors/types';
import type { Doc } from '../../models/misc';
import { selectToken } from '../../preferences/preferenceSlice';
import { useSourceKindFilter } from '../../settings/SourceKindFilter';
import type { AppDispatch } from '../../store';
import type {
  MultiSelectPopoverItem,
  MultiSelectPopoverProps,
} from '../MultiSelectPopover';
import { toSourcePickerItem, toSourcePickerItems } from '../sourcePickerItems';
import { IconButton } from '../ui/icon-button';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '../ui/breadcrumb';
import { folderRootLabel } from './folderCopy';
import {
  docFolderId,
  type KnowledgePick,
  pickRowIds,
  togglePick,
} from './folderPick';
import { loadFolders, selectFolderList } from './foldersSlice';
import {
  buildFolderTree,
  type FolderTree,
  folderPath,
  subtreeIds,
} from './folderTree';
import {
  buildKnowledgeRows,
  type UnlistedFolderRow,
} from './knowledgeFolderRows';
import type { Folder } from './types';

export type KnowledgeFolderPickerOptions = {
  /** Whether the picker is open: it opens at the root, search cleared. */
  open: boolean;
  /** The sources the reader can list. */
  docs: Doc[];
  pick: KnowledgePick;
  onPickChange: (next: KnowledgePick) => void;
  /** The reader's own connections, for the rows' lines and badges. */
  connections: Connection[];
  /** Text after a source's line ("Added by Lena"). */
  lineSuffix?: (doc: Doc) => string | null | undefined;
  /** Rows for picked sources the reader can't list (remove-only). */
  extraSources?: MultiSelectPopoverItem[];
  /** A picked folder the reader's tree doesn't hold: its row. */
  unlistedFolder?: (id: string) => Omit<UnlistedFolderRow, 'id'>;
};

/** What a knowledge picker passes on to `MultiSelectPopover`. */
export type KnowledgeFolderPopoverProps = Pick<
  MultiSelectPopoverProps,
  | 'items'
  | 'selectedIds'
  | 'onToggle'
  | 'filters'
  | 'header'
  | 'search'
  | 'onSearchChange'
  | 'shouldFilter'
  | 'selectedFirst'
  | 'onBack'
>;

/**
 * The caller's source folders as a tree, loaded once when nothing has asked
 * yet (the pickers' folder rows and the composer pill's name read it).
 */
export function useSourceFolderTree(): {
  tree: FolderTree;
  loaded: boolean;
  reload: () => void;
} {
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const list = useSelector(selectFolderList('source'));
  const tree = useMemo(() => buildFolderTree(list.items), [list.items]);
  const reload = () => void dispatch(loadFolders({ type: 'source', token }));
  useEffect(() => {
    if (!list.loaded && !list.loading && !list.failed)
      void dispatch(loadFolders({ type: 'source', token }));
  }, [list.loaded, list.loading, list.failed, dispatch, token]);
  return { tree, loaded: list.loaded, reload };
}

/**
 * The crumb row of an open folder in a picker, under the search: a back
 * button, then `Knowledge › Carriers` on one line (the root and parents open
 * their level, parents truncate first).
 */
export function PickerFolderCrumb({
  trail,
  onNavigate,
}: {
  trail: Folder[];
  onNavigate: (folderId: string | null) => void;
}) {
  const { t } = useTranslation();
  const parent = trail.length > 1 ? trail[trail.length - 2].id : null;
  return (
    <div
      data-slot="picker-folder-crumb"
      className="flex h-9 min-w-0 items-center gap-1 border-b px-2"
    >
      <IconButton
        variant="ghost"
        size="icon-xs"
        label={t('folders.picker.back')}
        icon={ChevronLeft}
        onClick={() => onNavigate(parent)}
      />
      <Breadcrumb className="min-w-0">
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <button type="button" onClick={() => onNavigate(null)}>
                {folderRootLabel(t, 'source')}
              </button>
            </BreadcrumbLink>
          </BreadcrumbItem>
          {trail.map((folder, index) => (
            <Fragment key={folder.id}>
              <BreadcrumbSeparator className="shrink-0" />
              <BreadcrumbItem>
                {index === trail.length - 1 ? (
                  <BreadcrumbPage>{folder.name}</BreadcrumbPage>
                ) : (
                  <BreadcrumbLink asChild>
                    <button
                      type="button"
                      title={folder.name}
                      onClick={() => onNavigate(folder.id)}
                    >
                      {folder.name}
                    </button>
                  </BreadcrumbLink>
                )}
              </BreadcrumbItem>
            </Fragment>
          ))}
        </BreadcrumbList>
      </Breadcrumb>
    </div>
  );
}

/**
 * A knowledge picker that knows folders (the chat composer, the agent
 * builder, a workflow agent node): whole folders pick as one live item, a
 * folder's chevron opens it, a search lists every level flat, and the kind
 * track counts what the open place holds. With no folders it lists the
 * sources as before (Yours / Shared with team, cmdk's search).
 *
 * Args:
 *   options: Whether it is open, the sources, the pick and its setter, and
 *     the extra rows for what the reader can't list.
 *
 * Returns:
 *   The props for `MultiSelectPopover` and the folder tree.
 */
export function useKnowledgeFolderPicker({
  open,
  docs,
  pick,
  onPickChange,
  connections,
  lineSuffix,
  extraSources,
  unlistedFolder,
}: KnowledgeFolderPickerOptions): {
  popoverProps: KnowledgeFolderPopoverProps;
  tree: FolderTree;
} {
  const { t } = useTranslation();
  const { tree, reload } = useSourceFolderTree();
  const [place, setPlace] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  // Each open starts at the root with an empty search, and reads the
  // folders again so the counts are the server's.
  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (open) {
      setPlace(null);
      setSearch('');
    }
  }
  // Only an open asks (reload is a new function every render).
  useEffect(() => {
    if (open) reload();
  }, [open]);
  // A folder deleted while it is open: back to the root.
  const openPlace = place && tree.byId.has(place) ? place : null;

  const placeDocs = useMemo(() => {
    if (!openPlace) return docs;
    const subtree = subtreeIds(tree, openPlace);
    return docs.filter((doc) => {
      const home = docFolderId(tree, doc);
      return home !== null && subtree.has(home);
    });
  }, [docs, tree, openPlace]);
  const kinds = useSourceKindFilter(placeDocs, open);

  const unlistedFolders = useMemo(
    () =>
      pick.folders
        .filter((id) => !tree.byId.has(id))
        .map((id) => ({
          id,
          ...(unlistedFolder?.(id) ?? { label: id }),
        })),
    [pick.folders, tree, unlistedFolder],
  );
  const hasFolders = tree.byId.size > 0 || pick.folders.length > 0;
  const flat = search.trim() !== '' || kinds.kind !== 'all';

  const items = useMemo<MultiSelectPopoverItem[]>(() => {
    const options = {
      t,
      labels: {
        own: t('conversation.sources.groupOwn'),
        team: t('conversation.sources.groupTeam'),
      },
      connections,
      lineSuffix,
    };
    if (!hasFolders)
      return [
        ...toSourcePickerItems(kinds.docs, options),
        ...(kinds.kind === 'all' ? (extraSources ?? []) : []),
      ];
    return buildKnowledgeRows({
      t,
      tree,
      docs,
      shownDocs: kinds.docs,
      pick,
      place: openPlace,
      query: search,
      kindFiltered: kinds.kind !== 'all',
      sourceRow: (doc, linePrefix) =>
        toSourcePickerItem(doc, { ...options, linePrefix }),
      extraSources: kinds.kind === 'all' ? extraSources : [],
      unlistedFolders,
      onOpen: (id) => {
        setPlace(id);
        setSearch('');
      },
    });
  }, [
    t,
    connections,
    lineSuffix,
    hasFolders,
    kinds.docs,
    kinds.kind,
    extraSources,
    tree,
    docs,
    pick,
    openPlace,
    search,
    unlistedFolders,
  ]);

  const trail = openPlace ? folderPath(tree, openPlace) : [];
  return {
    tree,
    popoverProps: {
      items,
      selectedIds: pickRowIds(pick),
      onToggle: (id) => {
        const next = togglePick(tree, docs, pick, id);
        if (next !== pick) onPickChange(next);
      },
      filters: kinds.filters,
      header: openPlace ? (
        <PickerFolderCrumb trail={trail} onNavigate={setPlace} />
      ) : undefined,
      search,
      onSearchChange: setSearch,
      shouldFilter: !hasFolders,
      // What was picked as it opened leads the root; a folder or a search
      // lists its own rows.
      selectedFirst: !openPlace && !(hasFolders && flat),
      onBack: openPlace
        ? () => setPlace(tree.parentOf.get(openPlace) ?? null)
        : undefined,
    },
  };
}
