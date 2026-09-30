import copy from 'copy-to-clipboard';
import { ChevronLeft, ChevronRight, Copy, Pencil, Trash2 } from 'lucide-react';
import React, { useEffect, useImperativeHandle, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { useDebouncedValue, useLoaderState } from '../hooks';
import { usePageSize } from '../hooks/usePageState';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { ChunkType } from '../settings/types';
import {
  abbreviateCount,
  chunkPreviewText,
  formatChunkTokens,
} from './chunkUtils';
import SearchInput from './SearchInput';
import SkeletonLoader from './SkeletonLoader';
import SourceMarkdown from './SourceMarkdown';
import PathHeader from './tree/PathHeader';
import ReaderPanel from './tree/ReaderPanel';
import SourceEditSheet from './tree/SourceEditSheet';
import { Alert, AlertDescription } from './ui/alert';
import { Button } from './ui/button';
import { Card, CardFooter } from './ui/card';
import { FormField } from './ui/form-field';
import { Input } from './ui/input';
import { ActionMenu } from './ui/dropdown-menu';
import { EmptyState } from './ui/empty-state';
import { IconButton } from './ui/icon-button';
import { Pagination, pageRangeParams } from './ui/pagination';

/** Chunks per page: divisible by 2, 3 and 4 columns, so a page fills the grid. */
const PAGE_SIZE_OPTIONS = [12, 24, 48];

/**
 * Where the open chunk is, as reported to an embedding host: its 1-based
 * position, 'unplaced' while it is open but its place in the list is unknown
 * (a save moved it off every probed position), or null while the grid shows.
 */
export type OpenChunkPosition = number | 'unplaced' | null;

/** Lets the host's crumbs close the open chunk (see TreeBrowser). */
export interface ChunksController {
  closeChunk: () => void;
}

const TILE_GRID =
  'grid grid-cols-1 gap-4 sm:grid-cols-[repeat(auto-fit,minmax(min(400px,100%),1fr))]';

/**
 * Whether a key press belongs to something else: a field being typed in, an
 * open dialog, drawer or menu.
 *
 * @param event The keydown event.
 * @returns True when the chunk arrows should leave the key alone.
 */
function keyBelongsElsewhere(event: KeyboardEvent): boolean {
  if (event.defaultPrevented) return true;
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)
    return true;
  const target = event.target as HTMLElement | null;
  if (
    target &&
    (target.isContentEditable ||
      ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
  )
    return true;
  return !!document.querySelector('[role="dialog"], [role="menu"]');
}

interface ChunksProps {
  documentId: string;
  documentName?: string;
  handleGoBack: () => void;
  path?: string;
  /** The open file's display name: a new chunk's default title. */
  fileName?: string;
  /** Extra header control (Test retrieval); standalone only. */
  headerAction?: React.ReactNode;
  /**
   * Rendered inside a source view that draws the header itself (TreeBrowser):
   * no PathHeader here. The host's crumbs show the open chunk
   * (`onOpenChunkChange`) and close it (`controllerRef`).
   */
  embedded?: boolean;
  /** Where the open chunk is; see {@link OpenChunkPosition}. */
  onOpenChunkChange?: (position: OpenChunkPosition) => void;
  controllerRef?: React.MutableRefObject<ChunksController | null>;
  /**
   * Whether the caller may change the source (`can(source, 'edit')`). False
   * hides Add chunk, Edit and Delete; reading, copying and paging stay.
   */
  canEdit?: boolean;
}

type SheetMode = 'edit' | 'add';

const Chunks: React.FC<ChunksProps> = ({
  documentId,
  documentName,
  handleGoBack,
  path,
  fileName,
  headerAction,
  embedded = false,
  onOpenChunkChange,
  controllerRef,
  canEdit = true,
}) => {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const [paginatedChunks, setPaginatedChunks] = useState<ChunkType[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = usePageSize(
    'DocsGPTPageSize:chunks',
    PAGE_SIZE_OPTIONS,
  );
  const [totalChunks, setTotalChunks] = useState(0);
  const [loading, setLoading] = useLoaderState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const debouncedSearchTerm = useDebouncedValue(searchTerm, 300);
  const [openChunk, setOpenChunk] = useState<ChunkType | null>(null);
  // The open chunk's position in the whole filtered list (1-based).
  const [openPosition, setOpenPosition] = useState(0);
  // Set when a save leaves the open chunk off every probed position: its
  // place in the list is unknown, so position labels and paging are off.
  const [positionLost, setPositionLost] = useState(false);
  // A previous / next fetch in flight.
  const [stepping, setStepping] = useState(false);
  const stepRef = useRef(0);
  const [sheetOpen, setSheetOpen] = useState(false);
  // Kept after closing so the title holds through the exit animation.
  const [sheetMode, setSheetMode] = useState<SheetMode>('add');
  const [draft, setDraft] = useState('');
  // The chunk's title: the name answers cite it by.
  const [draftTitle, setDraftTitle] = useState('');
  // A new chunk's default title as it was when the Add drawer opened: the
  // discard check compares against it, not a default a later fetch moved.
  const [addBaselineTitle, setAddBaselineTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [deleteModalState, setDeleteModalState] =
    useState<ActiveState>('INACTIVE');
  const [chunkToDelete, setChunkToDelete] = useState<ChunkType | null>(null);

  const showError = (message: string) =>
    dispatch(showActionToast({ variant: 'destructive', message }));

  const fileLabel = path || documentName || '';

  // Only the latest grid fetch may write: an older response (a refresh after
  // a save, a page just left) is dropped.
  const fetchRef = useRef(0);
  const fetchChunks = async () => {
    const request = ++fetchRef.current;
    setLoading(true);
    try {
      const response = await userService.getDocumentChunks(
        documentId,
        page,
        perPage,
        token,
        path,
        debouncedSearchTerm,
      );

      if (!response.ok) {
        throw new Error('Failed to fetch chunks data');
      }

      const data = await response.json();
      if (request !== fetchRef.current) return;

      setPage(data.page);
      setPerPage(data.per_page);
      setTotalChunks(data.total);
      setPaginatedChunks(data.chunks);
      setLoadFailed(false);
    } catch (error) {
      console.error(error);
      if (request !== fetchRef.current) return;
      setPaginatedChunks([]);
      setLoadFailed(true);
    } finally {
      if (request === fetchRef.current) setLoading(false);
    }
  };

  /**
   * Open chunk n of the current (searched, per-file) list: one chunk per
   * page, so the page number is the position.
   */
  const goToChunk = async (position: number) => {
    if (position < 1 || (totalChunks > 0 && position > totalChunks)) return;
    const request = ++stepRef.current;
    setStepping(true);
    try {
      const response = await userService.getDocumentChunks(
        documentId,
        position,
        1,
        token,
        path,
        debouncedSearchTerm,
      );
      if (!response.ok) throw new Error('Failed to fetch chunk');
      const data = await response.json();
      if (request !== stepRef.current) return;
      const chunk: ChunkType | undefined = data.chunks?.[0];
      if (typeof data.total === 'number') setTotalChunks(data.total);
      if (chunk) {
        setOpenChunk(chunk);
        setOpenPosition(position);
        setPositionLost(false);
      }
    } catch (error) {
      console.error(error);
      if (request === stepRef.current)
        showError(t('settings.sources.chunkErrors.load'));
    } finally {
      if (request === stepRef.current) setStepping(false);
    }
  };

  /**
   * After a save, find the edited chunk in the store's current order and show
   * its stored copy (fresh metadata) at that position, so "n of total" and
   * previous / next follow the list as it now is. Checked in turn: the open
   * position (the chunk stayed), then the last one (a store that re-adds the
   * copy at the end). Each probe matches by id, so no store ordering is
   * assumed. When neither holds it (moved elsewhere, or a search it no longer
   * matches), the saved text stays but its position is unknown, so the
   * position labels drop the number and previous / next are off until the
   * reader closes; the whole filtered list is never fetched. A failed or
   * superseded probe leaves what is shown.
   *
   * @param chunk The chunk just saved, with its new id.
   */
  const locateOpenChunk = async (chunk: ChunkType) => {
    const request = ++stepRef.current;
    const fetchPage = async (pageNumber: number, size: number) => {
      const response = await userService.getDocumentChunks(
        documentId,
        pageNumber,
        size,
        token,
        path,
        debouncedSearchTerm,
      );
      if (!response.ok) return null;
      const data = await response.json();
      return request === stepRef.current ? data : null;
    };
    const show = (stored: ChunkType, at: number, total: number) => {
      setTotalChunks(total);
      setOpenChunk(stored);
      setOpenPosition(at);
      setPositionLost(false);
    };
    try {
      const here = await fetchPage(openPosition, 1);
      if (!here) return;
      const total: number =
        typeof here.total === 'number' ? here.total : totalChunks;
      const stored: ChunkType | undefined = here.chunks?.[0];
      if (stored?.doc_id === chunk.doc_id) {
        show(stored, openPosition, total);
        return;
      }
      if (total >= 1 && total !== openPosition) {
        const last = await fetchPage(total, 1);
        if (!last) return;
        const lastChunk: ChunkType | undefined = last.chunks?.[0];
        if (lastChunk?.doc_id === chunk.doc_id) {
          show(lastChunk, total, total);
          return;
        }
      }
      setTotalChunks(total);
      setPositionLost(true);
    } catch (error) {
      console.error(error);
    }
  };

  /**
   * Back to the grid, on the page holding the chunk last open.
   *
   * @param total The chunk count to page against, when it just changed (a
   *   delete); the page is clamped to the last one that still exists.
   * @returns Whether the page changed (and so fetches by itself).
   */
  const closeChunk = (total = totalChunks) => {
    stepRef.current++;
    setStepping(false);
    const lastPage = Math.max(1, Math.ceil(total / perPage));
    const target = Math.min(
      lastPage,
      Math.max(1, Math.ceil(openPosition / perPage)),
    );
    setOpenChunk(null);
    if (target !== page) setPage(target);
    return target !== page;
  };

  useImperativeHandle(controllerRef, () => ({
    closeChunk: () => closeChunk(),
  }));

  const openChunkPosition: OpenChunkPosition = !openChunk
    ? null
    : positionLost
      ? 'unplaced'
      : openPosition;
  const onOpenChunkChangeRef = useRef(onOpenChunkChange);
  useEffect(() => {
    onOpenChunkChangeRef.current = onOpenChunkChange;
  });
  useEffect(() => {
    onOpenChunkChangeRef.current?.(openChunkPosition);
  }, [openChunkPosition]);
  useEffect(() => () => onOpenChunkChangeRef.current?.(null), []);

  const showChunk = (chunk: ChunkType, position: number) => {
    setOpenChunk(chunk);
    setOpenPosition(position);
    setPositionLost(false);
  };

  /**
   * A new chunk's title: the one this file's chunks are cited by, else the
   * file's name, as ingest sets it.
   */
  const defaultTitle = () =>
    paginatedChunks.find((chunk) => chunk.metadata?.title)?.metadata.title ||
    fileName ||
    path?.split('/').pop() ||
    documentName ||
    '';

  const openSheet = (mode: SheetMode) => {
    const baseline = mode === 'add' ? defaultTitle() : '';
    setDraft(mode === 'edit' ? openChunk?.text || '' : '');
    setDraftTitle(
      mode === 'edit' ? openChunk?.metadata?.title || '' : baseline,
    );
    setAddBaselineTitle(baseline);
    setSaveFailed(false);
    setSheetMode(mode);
    setSheetOpen(true);
  };

  const closeSheet = () => {
    setSheetOpen(false);
    setSaveFailed(false);
  };

  const handleAddChunk = async (text: string, title: string) => {
    if (!text.trim()) return;
    setSaving(true);
    setSaveFailed(false);
    try {
      const response = await userService.addChunk(
        {
          id: documentId,
          text,
          metadata: {
            source: path || documentName,
            source_id: documentId,
            title: title.trim(),
          },
        },
        token,
      );
      if (!response.ok) throw new Error('Failed to add chunk');
      closeSheet();
      fetchChunks();
    } catch (e) {
      console.error(e);
      setSaveFailed(true);
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateChunk = async (
    text: string,
    title: string,
    chunk: ChunkType,
  ) => {
    const savedTitle = chunk.metadata?.title || '';
    if (!text.trim()) return;
    if (text === (chunk.text || '') && title.trim() === savedTitle) return;
    setSaving(true);
    setSaveFailed(false);
    // The backend merges metadata: send a title only when the chunk had one
    // (clearing it sends '') or one was entered, never '' onto an untitled one.
    const sendTitle = !!savedTitle || !!title.trim();
    try {
      const response = await userService.updateChunk(
        {
          id: documentId,
          chunk_id: chunk.doc_id,
          text,
          ...(sendTitle ? { metadata: { title: title.trim() } } : {}),
        },
        token,
      );
      if (!response.ok) throw new Error('Failed to update chunk');
      const data = await response.json().catch(() => ({}));
      closeSheet();
      // Show the edit straight away (its token count is recomputed
      // server-side, so it is dropped until the reload), then find where the
      // store now keeps it. Most stores (FAISS, MongoDB, pgvector, Qdrant)
      // update in place: same id, same position. Only the base add-then-delete
      // fallback (Milvus) saves it under a new id, which can move it.
      const edited: ChunkType = {
        ...chunk,
        doc_id: data.chunk_id ?? chunk.doc_id,
        text,
        metadata: {
          ...chunk.metadata,
          ...(sendTitle ? { title: title.trim() } : {}),
          token_count: undefined,
        },
      };
      setOpenChunk(edited);
      locateOpenChunk(edited);
      fetchChunks();
    } catch (e) {
      console.error(e);
      setSaveFailed(true);
    } finally {
      setSaving(false);
    }
  };

  // Returned to ConfirmationModal through handleConfirmedDelete: it stays
  // pending while this runs and keeps a failure in the dialog.
  const handleDeleteChunk = async (chunk: ChunkType) => {
    const response = await userService.deleteChunk(
      documentId,
      chunk.doc_id,
      token,
    );
    if (!response.ok) throw new Error('Failed to delete chunk');
    // A page change fetches by itself; otherwise refresh this page.
    if (!closeChunk(Math.max(0, totalChunks - 1))) fetchChunks();
  };

  const confirmDeleteChunk = (chunk: ChunkType) => {
    setChunkToDelete(chunk);
    setDeleteModalState('ACTIVE');
  };

  const handleConfirmedDelete = async () => {
    if (!chunkToDelete) return;
    await handleDeleteChunk(chunkToDelete);
    setChunkToDelete(null);
  };

  const handleCancelDelete = () => {
    setDeleteModalState('INACTIVE');
    setChunkToDelete(null);
  };

  // One fetch per page, page size, file or search; a new search starts on
  // page 1 (that page change then fetches).
  const fetchedSearchRef = useRef(debouncedSearchTerm);
  useEffect(() => {
    if (fetchedSearchRef.current !== debouncedSearchTerm) {
      fetchedSearchRef.current = debouncedSearchTerm;
      if (page !== 1) {
        setPage(1);
        return;
      }
    }
    fetchChunks();
  }, [page, perPage, path, debouncedSearchTerm]);

  useEffect(() => {
    setSearchTerm('');
    setPage(1);
  }, [path]);

  const canGoPrevious =
    !!openChunk && !stepping && !positionLost && openPosition > 1;
  const canGoNext =
    !!openChunk && !stepping && !positionLost && openPosition < totalChunks;

  // ← / → walk the chunks while nothing else owns the keys.
  const goToChunkRef = useRef(goToChunk);
  goToChunkRef.current = goToChunk;
  useEffect(() => {
    if (!openChunk || sheetOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      if (keyBelongsElsewhere(event)) return;
      if (event.key === 'ArrowLeft' && !canGoPrevious) return;
      if (event.key === 'ArrowRight' && !canGoNext) return;
      event.preventDefault();
      goToChunkRef.current(openPosition + (event.key === 'ArrowLeft' ? -1 : 1));
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [openChunk, sheetOpen, canGoPrevious, canGoNext, openPosition]);

  // Standalone (a non-nested source): Sources, the source, then the open
  // chunk; the source crumb closes the chunk, the Sources crumb leaves.
  const renderHeader = () => (
    <PathHeader
      root={{ label: t('settings.sources.label'), onSelect: handleGoBack }}
      segments={[
        {
          label: documentName ?? '',
          onSelect: openChunk ? () => closeChunk() : undefined,
        },
        ...(openChunk
          ? [
              {
                label: positionLost
                  ? t('settings.sources.chunkCrumbUnplaced')
                  : t('settings.sources.chunkCrumb', { n: openPosition }),
              },
            ]
          : []),
      ]}
      byline={
        loading && totalChunks === 0
          ? undefined
          : t('settings.sources.chunkCount', {
              count: totalChunks,
              formatted: abbreviateCount(totalChunks),
            })
      }
      actions={headerAction}
    />
  );

  const renderToolbar = () => (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
      <div className="w-full min-w-0 sm:max-w-md sm:flex-1">
        <SearchInput
          label={t('settings.sources.searchChunks')}
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
      </div>
      {/* Standalone, the header's byline already shows the count. */}
      {embedded && !(loading && totalChunks === 0) ? (
        <p className="text-muted-foreground text-sm whitespace-nowrap">
          {t('settings.sources.chunkCount', {
            count: totalChunks,
            formatted: abbreviateCount(totalChunks),
          })}
        </p>
      ) : null}
      {canEdit ? (
        <Button
          type="button"
          size="field"
          shape="pill"
          className="sm:ml-auto"
          onClick={() => openSheet('add')}
        >
          {t('settings.sources.addChunk')}
        </Button>
      ) : null}
    </div>
  );

  const renderList = () => {
    if (loading) {
      return (
        <div className={TILE_GRID}>
          <SkeletonLoader component="chunkCards" count={perPage} />
        </div>
      );
    }
    if (loadFailed) {
      return (
        <EmptyState
          tone="destructive"
          illustration="none"
          title={t('settings.sources.chunkErrors.load')}
          onRetry={() => fetchChunks()}
        />
      );
    }
    return (
      <div className={TILE_GRID}>
        {paginatedChunks.length === 0 ? (
          <EmptyState
            size="sm"
            title={t('settings.sources.noChunks')}
            className="col-span-full min-h-[50svh] w-full"
          />
        ) : (
          paginatedChunks.map((chunk, index) => {
            const position = (page - 1) * perPage + index + 1;
            return (
              <Card
                key={chunk.doc_id}
                variant="filled"
                padding="lg"
                interactive
                asChild
                className="h-50 w-full justify-between"
              >
                <button
                  type="button"
                  onClick={() => showChunk(chunk, position)}
                >
                  <p className="text-foreground line-clamp-6 text-sm leading-5 font-normal">
                    {chunkPreviewText(chunk.text)}
                  </p>
                  <CardFooter>
                    {t('settings.sources.chunkTileMeta', {
                      n: position,
                      tokens: formatChunkTokens(chunk.metadata),
                    })}
                  </CardFooter>
                </button>
              </Card>
            );
          })
        )}
      </div>
    );
  };

  const renderOpenChunk = (chunk: ChunkType) => (
    <ReaderPanel
      meta={
        <span>
          {positionLost
            ? t('settings.sources.chunkPositionUnplaced', {
                tokens: formatChunkTokens(chunk.metadata),
              })
            : t('settings.sources.chunkPosition', {
                n: openPosition,
                total: totalChunks,
                tokens: formatChunkTokens(chunk.metadata),
              })}
        </span>
      }
      actions={
        <>
          <IconButton
            variant="ghost-muted"
            size="icon-sm"
            shape="pill"
            label={t('settings.sources.previousChunk')}
            icon={ChevronLeft}
            side="bottom"
            disabled={!canGoPrevious}
            onClick={() => goToChunk(openPosition - 1)}
          />
          <IconButton
            variant="ghost-muted"
            size="icon-sm"
            shape="pill"
            label={t('settings.sources.nextChunk')}
            icon={ChevronRight}
            side="bottom"
            disabled={!canGoNext}
            onClick={() => goToChunk(openPosition + 1)}
          />
          {canEdit ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              shape="pill"
              onClick={() => openSheet('edit')}
            >
              <Pencil />
              {t('modals.chunk.edit')}
            </Button>
          ) : null}
          <ActionMenu
            size="toolbar"
            triggerLabel={t('settings.sources.menuAlt')}
            options={[
              {
                icon: Copy,
                label: t('settings.sources.copyText'),
                onClick: () => {
                  copy(chunk.text || '');
                  dispatch(
                    showActionToast({
                      variant: 'success',
                      message: t('conversation.copied'),
                    }),
                  );
                },
              },
              ...(canEdit
                ? [
                    {
                      icon: Trash2,
                      label: t('modals.chunk.delete'),
                      variant: 'destructive' as const,
                      onClick: () => confirmDeleteChunk(chunk),
                    },
                  ]
                : []),
            ]}
          />
        </>
      }
    >
      <SourceMarkdown content={chunk.text || ''} />
    </ReaderPanel>
  );

  const editing = sheetMode === 'edit' && !!openChunk;
  const savedText = editing ? openChunk?.text || '' : '';
  const savedTitle = editing
    ? openChunk?.metadata?.title || ''
    : addBaselineTitle;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {embedded ? null : renderHeader()}
      {openChunk ? (
        renderOpenChunk(openChunk)
      ) : (
        <div className="flex flex-col gap-4">
          {renderToolbar()}
          {renderList()}
          {!loading && !loadFailed ? (
            <Pagination
              page={page}
              pageSize={perPage}
              total={totalChunks}
              pageSizeOptions={PAGE_SIZE_OPTIONS}
              rangeLabel={(range) =>
                t('settings.sources.chunkRange', pageRangeParams(range))
              }
              onPageChange={setPage}
              onPageSizeChange={(rows) => {
                setPerPage(rows);
                setPage(1);
              }}
            />
          ) : null}
        </div>
      )}

      <SourceEditSheet
        open={sheetOpen}
        onClose={closeSheet}
        title={
          editing
            ? t('settings.sources.editChunk')
            : t('settings.sources.addChunk')
        }
        description={
          !editing
            ? fileLabel || undefined
            : positionLost
              ? t('settings.sources.editChunkDescriptionUnplaced', {
                  file: fileLabel,
                  tokens: formatChunkTokens(openChunk?.metadata),
                  interpolation: { escapeValue: false },
                })
              : t('settings.sources.editChunkDescription', {
                  file: fileLabel,
                  n: openPosition,
                  tokens: formatChunkTokens(openChunk?.metadata),
                  interpolation: { escapeValue: false },
                })
        }
        value={draft}
        onChange={setDraft}
        dirty={draft !== savedText || draftTitle.trim() !== savedTitle}
        onSave={() =>
          editing && openChunk
            ? handleUpdateChunk(draft, draftTitle, openChunk)
            : handleAddChunk(draft, draftTitle)
        }
        fields={
          <FormField
            label={t('modals.chunk.title')}
            hint={t('settings.sources.chunkTitleHint')}
            labelSurface="background"
          >
            <Input
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
              disabled={saving}
            />
          </FormField>
        }
        saving={saving}
        saveLabel={editing ? t('modals.chunk.save') : t('modals.chunk.add')}
        alert={
          saveFailed ? (
            <Alert variant="destructive">
              <AlertDescription>
                {editing
                  ? t('settings.sources.chunkErrors.save')
                  : t('settings.sources.chunkErrors.add')}
              </AlertDescription>
            </Alert>
          ) : undefined
        }
        fieldLabel={t('modals.chunk.bodyText')}
      />

      <ConfirmationModal
        message={t('modals.chunk.deleteConfirmation')}
        modalState={deleteModalState}
        setModalState={setDeleteModalState}
        handleSubmit={handleConfirmedDelete}
        error={t('settings.sources.chunkErrors.delete')}
        handleCancel={handleCancelDelete}
        submitLabel={t('modals.chunk.delete')}
        variant="destructive"
      />
    </div>
  );
};

export default Chunks;
