import {
  ChevronRight,
  Database,
  Folder as FolderIcon,
  User,
} from 'lucide-react';
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { useMediaQuery } from '../../hooks';
import { cn } from '@/lib/utils';
import { Alert, AlertDescription } from '../ui/alert';
import { Badge } from '../ui/badge';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '../ui/breadcrumb';
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '../ui/command';
import { EmptyState } from '../ui/empty-state';
import { IconButton } from '../ui/icon-button';
import { LoadingState } from '../ui/loading-state';
import { Modal, ModalActions } from '../ui/modal';
import {
  folderCountLine,
  folderErrorMessage,
  folderRootLabel,
} from './folderCopy';
import FolderNameModal from './FolderNameModal';
import { selectFolderList } from './foldersSlice';
import {
  buildFolderTree,
  canCreateIn,
  childFolders,
  folderMoveCheck,
  folderPath,
  formatFolderPath,
  subtreeIds,
} from './folderTree';
import NewFolderButton from './NewFolderButton';
import type { Folder, FolderType } from './types';
import { useFolderActions } from './useFolderActions';

// cmdk keys rows by `value`: the root row needs one no folder id can take.
const ROOT_ROW_VALUE = '__docsgpt-no-folder__';

/** What the dialog moves: items of the type (one or many) or a folder. */
export type MoveSubject =
  | {
      kind: 'items';
      ids: string[];
      /** Shown in the title: the item's name as stored. */
      name: string;
      /** Where the items are filed now (null: no folder). */
      folderId: string | null;
    }
  | { kind: 'folder'; folder: Folder };

export type MoveToFolderModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  type: FolderType;
  subject: MoveSubject;
  /** After the server moved it and the folder list reloaded. */
  onMoved?: (folderId: string | null) => void;
};

type RowState = 'ok' | 'current' | 'too_deep';

/**
 * Move to folder, for agents, sources and folders alike: a search over every
 * folder, the root as the first row ("My agents" / "Knowledge", no folder),
 * folder rows with a chevron into their subfolders, the current place marked
 * Current and disabled, and targets a folder move would push past three
 * levels disabled as Too deep. New folder makes one at the level open; a
 * failed move stays in the dialog as an Alert.
 */
export default function MoveToFolderModal({
  open,
  onOpenChange,
  type,
  subject,
  onMoved,
}: MoveToFolderModalProps) {
  const { t } = useTranslation();
  const { isMobile } = useMediaQuery();
  const list = useSelector(selectFolderList(type));
  const actions = useFolderActions(type);
  const tree = useMemo(() => buildFolderTree(list.items), [list.items]);

  // The level open in the list (null: the top level).
  const [level, setLevel] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  // The chosen target: a folder id, null for the root, undefined for none.
  const [target, setTarget] = useState<string | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [creating, setCreating] = useState(false);
  const generation = useRef(0);

  const movingFolder = subject.kind === 'folder' ? subject.folder : null;
  const current =
    subject.kind === 'folder'
      ? (tree.parentOf.get(subject.folder.id) ?? subject.folder.parent_id)
      : subject.folderId;
  const name = subject.kind === 'folder' ? subject.folder.name : subject.name;

  useEffect(() => {
    generation.current += 1;
    if (!open) return;
    setLevel(null);
    setQuery('');
    setTarget(undefined);
    setError(null);
    setPending(false);
    if (!list.loaded && !list.loading) actions.reload();
  }, [open]);

  // A folder can't go into itself or below it, so its subtree is left out.
  const excluded = useMemo(
    () =>
      movingFolder ? subtreeIds(tree, movingFolder.id) : new Set<string>(),
    [tree, movingFolder],
  );

  const rowState = (id: string | null): RowState => {
    if (id === (current ?? null)) return 'current';
    if (
      movingFolder &&
      folderMoveCheck(tree, movingFolder.id, id) === 'too_deep'
    )
      return 'too_deep';
    return 'ok';
  };

  const visibleChildren = (parentId: string | null): Folder[] =>
    childFolders(tree, parentId).filter((folder) => !excluded.has(folder.id));

  const searching = query.trim().length > 0;
  const needle = query.trim().toLowerCase();
  const rootLabel = folderRootLabel(t, type);

  const rows: Folder[] = searching
    ? list.items
        .filter((folder) => !excluded.has(folder.id))
        .filter((folder) => folder.name.toLowerCase().includes(needle))
        .sort((a, b) =>
          formatFolderPath(folderPath(tree, a.id)).localeCompare(
            formatFolderPath(folderPath(tree, b.id)),
          ),
        )
    : visibleChildren(level);
  const showRoot = !searching || rootLabel.toLowerCase().includes(needle);
  const trail = folderPath(tree, level);

  const submit = async () => {
    if (pending || target === undefined) return;
    const issued = generation.current;
    setPending(true);
    setError(null);
    try {
      if (subject.kind === 'folder')
        await actions.move(subject.folder.id, target);
      else await actions.fileItems(subject.ids, target);
      if (issued !== generation.current) return;
      onOpenChange(false);
      onMoved?.(target);
    } catch (reason) {
      if (issued !== generation.current) return;
      setPending(false);
      setError(folderErrorMessage(t, reason, 'folders.errors.moveFailed'));
    }
  };

  const stateLabel = (state: RowState) =>
    state === 'current' ? (
      <Badge variant="neutral">{t('folders.current')}</Badge>
    ) : state === 'too_deep' ? (
      <Badge variant="neutral">{t('folders.tooDeep')}</Badge>
    ) : null;

  const RootIcon = type === 'agent' ? User : Database;
  const rootState = rowState(null);

  const body = !list.loaded ? (
    list.failed ? (
      <EmptyState
        size="xs"
        illustration="none"
        tone="destructive"
        title={t('folders.errors.loadFailed')}
        onRetry={() => actions.reload()}
      />
    ) : (
      <LoadingState fill="block" size="sm" />
    )
  ) : (
    <CommandList
      label={t('folders.moveToFolder')}
      className={cn(isMobile ? 'max-h-none' : 'max-h-72 min-h-50')}
    >
      <CommandGroup>
        {showRoot && (
          <CommandItem
            value={ROOT_ROW_VALUE}
            disabled={rootState !== 'ok'}
            checked={target === null}
            aria-checked={target === null}
            onSelect={() => setTarget(null)}
          >
            <RootIcon className="size-5" aria-hidden="true" />
            <span className="min-w-0 truncate">{rootLabel}</span>
            <span className="text-muted-foreground shrink-0 text-xs">
              {t('folders.noFolder')}
            </span>
            <span className="ml-auto flex shrink-0 items-center">
              {stateLabel(rootState)}
            </span>
          </CommandItem>
        )}
        {rows.map((folder) => {
          const state = rowState(folder.id);
          const parents = searching
            ? folderPath(tree, folder.id).slice(0, -1)
            : [];
          const openable = !searching && visibleChildren(folder.id).length > 0;
          return (
            <CommandItem
              key={folder.id}
              value={folder.id}
              disabled={state !== 'ok'}
              checked={target === folder.id}
              aria-checked={target === folder.id}
              onSelect={() => setTarget(folder.id)}
            >
              <FolderIcon className="size-5" aria-hidden="true" />
              <span
                className="min-w-0 truncate"
                title={formatFolderPath([...parents, folder])}
              >
                {parents.length > 0 ? (
                  <span className="text-muted-foreground">
                    {formatFolderPath(parents)}
                    {' › '}
                  </span>
                ) : null}
                {folder.name}
              </span>
              <span className="text-muted-foreground shrink-0 text-xs">
                {folderCountLine(t, folder, type)}
              </span>
              <span className="ml-auto flex shrink-0 items-center gap-2">
                {stateLabel(state)}
                {openable && (
                  <IconButton
                    variant="ghost-on-accent"
                    size="icon-xs"
                    // A disabled row takes no pointer events; its chevron
                    // still opens the folder (move into a subfolder of the
                    // current one).
                    className="pointer-events-auto"
                    label={t('folders.openFolder', {
                      name: folder.name,
                      interpolation: { escapeValue: false },
                    })}
                    onClick={(e) => {
                      // Keep cmdk's row click from choosing the folder.
                      e.stopPropagation();
                      setLevel(folder.id);
                    }}
                    onKeyDown={(e) => {
                      // cmdk's root handles Enter by choosing the highlighted
                      // row; stop it here so Enter opens the folder instead.
                      if (e.key === 'Enter') e.stopPropagation();
                    }}
                  >
                    <ChevronRight className="text-current" aria-hidden="true" />
                  </IconButton>
                )}
              </span>
            </CommandItem>
          );
        })}
        {rows.length === 0 && !showRoot ? (
          <EmptyState
            size="xs"
            illustration="none"
            title={t('folders.noMatches')}
          />
        ) : rows.length === 0 && level !== null ? (
          <EmptyState
            size="xs"
            illustration="none"
            title={t('folders.noSubfolders')}
          />
        ) : null}
      </CommandGroup>
    </CommandList>
  );

  return (
    <>
      <Modal
        open={open}
        onOpenChange={onOpenChange}
        size="lg"
        title={t('folders.moveTitle', {
          name,
          interpolation: { escapeValue: false },
        })}
        footer={
          <ModalActions
            cancelLabel={t('cancel')}
            onCancel={() => onOpenChange(false)}
            submitLabel={t('folders.move')}
            onSubmit={submit}
            pending={pending}
            disabled={target === undefined}
            footerStart={
              <NewFolderButton
                look="dialog"
                atDepthLimit={!canCreateIn(tree, level)}
                onClick={() => setCreating(true)}
              />
            }
          />
        }
      >
        <Command shouldFilter={false} label={t('folders.moveToFolder')}>
          <div className="flex flex-col gap-3">
            <CommandInput
              variant="field"
              value={query}
              onValueChange={setQuery}
              placeholder={t('folders.searchFolders')}
              aria-label={t('folders.searchFolders')}
              autoFocus={!isMobile}
            />
            {!searching && level !== null ? (
              <Breadcrumb>
                <BreadcrumbList>
                  <BreadcrumbItem>
                    <BreadcrumbLink asChild>
                      <button type="button" onClick={() => setLevel(null)}>
                        {rootLabel}
                      </button>
                    </BreadcrumbLink>
                  </BreadcrumbItem>
                  {trail.map((folder, index) => (
                    <Fragment key={folder.id}>
                      <BreadcrumbSeparator />
                      <BreadcrumbItem>
                        {index === trail.length - 1 ? (
                          <BreadcrumbPage>{folder.name}</BreadcrumbPage>
                        ) : (
                          <BreadcrumbLink asChild>
                            <button
                              type="button"
                              title={folder.name}
                              onClick={() => setLevel(folder.id)}
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
            ) : null}
            {error ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            {body}
          </div>
        </Command>
      </Modal>
      <FolderNameModal
        open={creating}
        onOpenChange={setCreating}
        type={type}
        mode="create"
        parentId={level}
        onSaved={(folder) => {
          setQuery('');
          setTarget(folder.id);
        }}
      />
    </>
  );
}
