import copy from 'copy-to-clipboard';
import {
  ChevronLeft,
  ChevronRight,
  Copy,
  Pencil,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import React, {
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { useDebouncedValue, useLoaderState } from '../hooks';
import { usePageSize } from '../hooks/usePageState';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { ChunkInjection, ChunkType } from '../settings/types';
import {
  abbreviateCount,
  chunkPreviewText,
  formatChunkTokens,
  isSourceBusy,
  type LinkedChunk,
} from './chunkUtils';
import SearchInput from './SearchInput';
import SkeletonLoader from './SkeletonLoader';
import SourceMarkdown from './SourceMarkdown';
import PathHeader from './tree/PathHeader';
import ReaderPanel from './tree/ReaderPanel';
import SourceEditSheet from './tree/SourceEditSheet';
import { Alert, AlertDescription } from './ui/alert';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardFooter } from './ui/card';
import { FormField } from './ui/form-field';
import { Input } from './ui/input';
import { ActionMenu } from './ui/dropdown-menu';
import { EmptyState } from './ui/empty-state';
import { IconButton } from './ui/icon-button';
import { Label } from './ui/label';
import { Pagination, pageRangeParams } from './ui/pagination';
import { Switch } from './ui/switch';

/** Chunks per page: divisible by 2, 3 and 4 columns, so a page fills the grid. */
const PAGE_SIZE_OPTIONS = [12, 24, 48];
// How many pages of a linked chunk's search to look through for its id; each
// page is a scan of the whole source on the server.
const LINKED_SEARCH_PAGES = 10;

/**
 * Where the open chunk is, as reported to an embedding host: its 1-based
 * position, 'unplaced' while it is open but its place in the list is unknown
 * (a save moved it off every probed position), or null while the grid shows.
 */
export type OpenChunkPosition = number | 'unplaced' | null;

/** Lets the host's crumbs close the open chunk (see TreeBrowser). */
export interface ChunksController {
  closeChunk: () => void;
  /**
   * Lists the file again after its content changed elsewhere (a refreshed
   * web page): the open chunk closes, since its id is gone.
   */
  reload: () => void;
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
  /** The source's ⋯, last in the title row; standalone only. */
  headerMenu?: React.ReactNode;
  /**
   * Rendered inside a source view that draws the header itself (TreeBrowser):
   * no PathHeader here. The host's crumbs show the open chunk
   * (`onOpenChunkChange`) and close it (`controllerRef`).
   */
  embedded?: boolean;
  /** Where the open chunk is; see {@link OpenChunkPosition}. */
  onOpenChunkChange?: (position: OpenChunkPosition) => void;
  /**
   * The whole list's chunk count, whenever it is read (not while a search
   * or the flagged filter narrows it): the host's item bar shows it.
   */
  onTotalChange?: (total: number) => void;
  controllerRef?: React.MutableRefObject<ChunksController | null>;
  /**
   * Whether the caller may change the source (`can(source, 'edit')`). False
   * hides Add chunk, Edit and Delete; reading, copying and paging stay.
   */
  canEdit?: boolean;
  /**
   * A chunk to open in the reader once it is listed (a citation opened in
   * Knowledge): the list starts on its search, and the hit with its id opens
   * (paging on to find it), else the first hit. Applied once; after that the
   * list behaves as usual.
   */
  linkedChunk?: Pick<LinkedChunk, 'id' | 'search'>;
}

type SheetMode = 'edit' | 'add';

/** Why a save failed: the source was busy (a page change or sync), or else. */
type SaveError = 'busy' | 'failed' | null;

/** A delete the source turned away while a page change or sync held it. */
class SourceBusy extends Error {}

/** Whether the chunk's cached prompt-injection score is flagged (suspected or high). */
const isFlagged = (injection?: ChunkInjection | null): boolean =>
  Boolean(injection?.level);

/**
 * A flagged chunk's badge: likely or possible prompt injection, or marked
 * safe once its source's owner allowed it. Nothing for a clean chunk.
 */
function InjectionBadge({ injection }: { injection?: ChunkInjection | null }) {
  const { t } = useTranslation();
  if (!injection?.level) return null;
  if (injection.allowed)
    return (
      <Badge variant="neutral">
        {t('settings.sources.injection.markedSafe')}
      </Badge>
    );
  return (
    <Badge variant="warning">
      {t(
        injection.level === 'high'
          ? 'settings.sources.injection.high'
          : 'settings.sources.injection.suspected',
      )}
    </Badge>
  );
}

const Chunks: React.FC<ChunksProps> = ({
  documentId,
  documentName,
  handleGoBack,
  path,
  fileName,
  headerAction,
  headerMenu,
  embedded = false,
  onOpenChunkChange,
  onTotalChange,
  controllerRef,
  canEdit = true,
  linkedChunk,
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
  const [searchTerm, setSearchTerm] = useState<string>(
    linkedChunk?.search ?? '',
  );
  const linkedOpenedRef = useRef(!linkedChunk);
  // The linked search's first hit, opened when no page holds the id.
  const linkedFirstHitRef = useRef<ChunkType | null>(null);
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
  const [saveError, setSaveError] = useState<SaveError>(null);
  const [deleteModalState, setDeleteModalState] =
    useState<ActiveState>('INACTIVE');
  const [chunkToDelete, setChunkToDelete] = useState<ChunkType | null>(null);
  // Only the chunks whose cached prompt-injection score is flagged
  // (`injection=flagged`); a chunk is scored once a chat retrieves it.
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const flaggedOnlyId = useId();
  const injection = flaggedOnly ? 'flagged' : undefined;

  const showError = (message: string) =>
    dispatch(showActionToast({ variant: 'destructive', message }));

  const fileLabel = path || documentName || '';

  const onTotalChangeRef = useRef(onTotalChange);
  onTotalChangeRef.current = onTotalChange;
  /**
   * Keeps a count the server just gave; the whole list's (no search, no
   * flagged filter, as the request that read it) goes to the host too.
   */
  const recordTotal = (total: number) => {
    setTotalChunks(total);
    if (!debouncedSearchTerm && !injection) onTotalChangeRef.current?.(total);
  };

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
        injection,
      );

      if (!response.ok) {
        throw new Error('Failed to fetch chunks data');
      }

      const data = await response.json();
      if (request !== fetchRef.current) return;

      setPage(data.page);
      setPerPage(data.per_page);
      recordTotal(data.total);
      setPaginatedChunks(data.chunks);
      setLoadFailed(false);
      if (!linkedOpenedRef.current) {
        const hits: ChunkType[] = data.chunks ?? [];
        const index = hits.findIndex(
          (chunk) => chunk.doc_id === linkedChunk?.id,
        );
        if (data.page === 1) linkedFirstHitRef.current = hits[0] ?? null;
        const lastPage = Math.min(
          Math.ceil(data.total / data.per_page),
          LINKED_SEARCH_PAGES,
        );
        // Chunks sharing the excerpt's start (a repeated header) can push the
        // cited one past the first page: look on before settling for another.
        if (index === -1 && linkedChunk?.id && data.page < lastPage) {
          setPage(data.page + 1);
          return;
        }
        linkedOpenedRef.current = true;
        if (index !== -1) {
          showChunk(hits[index], (data.page - 1) * data.per_page + index + 1);
        } else if (linkedFirstHitRef.current) {
          // The id moved (a re-chunked source): the search's first hit.
          showChunk(linkedFirstHitRef.current, 1);
        }
      }
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
        injection,
      );
      if (!response.ok) throw new Error('Failed to fetch chunk');
      const data = await response.json();
      if (request !== stepRef.current) return;
      const chunk: ChunkType | undefined = data.chunks?.[0];
      if (typeof data.total === 'number') recordTotal(data.total);
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
        injection,
      );
      if (!response.ok) return null;
      const data = await response.json();
      return request === stepRef.current ? data : null;
    };
    const show = (stored: ChunkType, at: number, total: number) => {
      recordTotal(total);
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
      recordTotal(total);
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

  // By the mode alone, so a closing edit drawer keeps its title.
  const editing = sheetMode === 'edit';
  const savedText = editing ? openChunk?.text || '' : '';
  const savedTitle = editing
    ? openChunk?.metadata?.title || ''
    : addBaselineTitle;
  const sheetDirty = draft !== savedText || draftTitle.trim() !== savedTitle;

  const reload = () => {
    stepRef.current++;
    setStepping(false);
    setOpenChunk(null);
    setPositionLost(false);
    void fetchChunks();
  };

  // A reload that came while the edit drawer held unsaved text: it runs once
  // the drawer closes, so the edit is never turned into a new chunk.
  const reloadPendingRef = useRef(false);
  useEffect(() => {
    if (sheetOpen || !reloadPendingRef.current) return;
    reloadPendingRef.current = false;
    reload();
  }, [sheetOpen]);

  useImperativeHandle(controllerRef, () => ({
    closeChunk: () => closeChunk(),
    reload: () => {
      if (sheetOpen && editing) {
        // The open chunk's id may be gone: unsaved text waits, a clean
        // drawer closes with it.
        if (sheetDirty) {
          reloadPendingRef.current = true;
          return;
        }
        closeSheet();
      }
      reload();
    },
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
    setSaveError(null);
    setSheetMode(mode);
    setSheetOpen(true);
  };

  const closeSheet = () => {
    setSheetOpen(false);
    setSaveError(null);
  };

  const handleAddChunk = async (text: string, title: string) => {
    if (!text.trim()) return;
    setSaving(true);
    setSaveError(null);
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
      if (!response.ok) {
        setSaveError((await isSourceBusy(response)) ? 'busy' : 'failed');
        return;
      }
      closeSheet();
      fetchChunks();
    } catch (e) {
      console.error(e);
      setSaveError('failed');
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
    setSaveError(null);
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
      if (!response.ok) {
        setSaveError((await isSourceBusy(response)) ? 'busy' : 'failed');
        return;
      }
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
      setSaveError('failed');
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
    if (!response.ok) {
      if (await isSourceBusy(response)) throw new SourceBusy();
      throw new Error('Failed to delete chunk');
    }
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

  /**
   * Mark the chunk's text safe from prompt-injection screening for this
   * source (`allow`), or undo it (`clear`); the reader and its tile show the
   * new state.
   */
  const reviewInjection = async (
    chunk: ChunkType,
    decision: 'allow' | 'clear',
  ) => {
    const hash = chunk.injection?.content_hash;
    if (!hash) return;
    setReviewing(true);
    try {
      const response = await userService.reviewChunkInjection(
        documentId,
        hash,
        decision,
        token,
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.success) throw new Error('review failed');
      const reviewed = (item: ChunkType): ChunkType =>
        item.injection?.content_hash === hash
          ? { ...item, injection: { ...item.injection, allowed: data.allowed } }
          : item;
      setOpenChunk((current) => (current ? reviewed(current) : current));
      setPaginatedChunks((current) => current.map(reviewed));
    } catch (error) {
      console.error(error);
      showError(t('settings.sources.injection.reviewFailed'));
    } finally {
      setReviewing(false);
    }
  };

  // One fetch per page, page size, file, search or flagged filter; a new
  // search or filter starts on page 1 (that page change then fetches).
  const fetchedSearchRef = useRef(debouncedSearchTerm);
  const fetchedFlaggedRef = useRef(flaggedOnly);
  useEffect(() => {
    if (
      fetchedSearchRef.current !== debouncedSearchTerm ||
      fetchedFlaggedRef.current !== flaggedOnly
    ) {
      fetchedSearchRef.current = debouncedSearchTerm;
      fetchedFlaggedRef.current = flaggedOnly;
      if (page !== 1) {
        setPage(1);
        return;
      }
    }
    fetchChunks();
  }, [page, perPage, path, debouncedSearchTerm, flaggedOnly]);

  // Another file starts unsearched on page 1; the first render keeps the
  // linked chunk's search.
  const listedPathRef = useRef(path);
  useEffect(() => {
    if (listedPathRef.current === path) return;
    listedPathRef.current = path;
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
      menu={headerMenu}
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
      {/* Offered while the chunks carry scores (the operator has the model on). */}
      {flaggedOnly || paginatedChunks.some((chunk) => chunk.injection) ? (
        <div className="flex items-center gap-2">
          <Switch
            id={flaggedOnlyId}
            checked={flaggedOnly}
            data-testid="chunks-flagged-only"
            onCheckedChange={setFlaggedOnly}
          />
          <Label htmlFor={flaggedOnlyId} className="whitespace-nowrap">
            {t('settings.sources.injection.flaggedOnly')}
          </Label>
        </div>
      ) : null}
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
            title={
              flaggedOnly
                ? t('settings.sources.injection.noFlagged')
                : t('settings.sources.noChunks')
            }
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
                  <CardFooter className="flex-wrap">
                    {t('settings.sources.chunkTileMeta', {
                      n: position,
                      tokens: formatChunkTokens(chunk.metadata),
                    })}
                    <InjectionBadge injection={chunk.injection} />
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
          {canEdit &&
          isFlagged(chunk.injection) &&
          !chunk.injection?.allowed ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              shape="pill"
              loading={reviewing}
              data-testid="chunk-mark-safe"
              onClick={() => reviewInjection(chunk, 'allow')}
            >
              <ShieldCheck />
              {t('settings.sources.injection.markSafe')}
            </Button>
          ) : null}
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
      {chunk.injection ? (
        <InjectionNotice
          injection={chunk.injection}
          canUndo={canEdit}
          busy={reviewing}
          onUndo={() => reviewInjection(chunk, 'clear')}
        />
      ) : null}
      <SourceMarkdown content={chunk.text || ''} />
    </ReaderPanel>
  );

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
          !editing || !openChunk
            ? fileLabel || undefined
            : positionLost
              ? t('settings.sources.editChunkDescriptionUnplaced', {
                  file: fileLabel,
                  tokens: formatChunkTokens(openChunk.metadata),
                  interpolation: { escapeValue: false },
                })
              : t('settings.sources.editChunkDescription', {
                  file: fileLabel,
                  n: openPosition,
                  tokens: formatChunkTokens(openChunk.metadata),
                  interpolation: { escapeValue: false },
                })
        }
        value={draft}
        onChange={setDraft}
        dirty={sheetDirty}
        onSave={() => {
          // An edit drawer never saves as a new chunk, even with no chunk open.
          if (!editing) void handleAddChunk(draft, draftTitle);
          else if (openChunk)
            void handleUpdateChunk(draft, draftTitle, openChunk);
        }}
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
          saveError ? (
            <Alert variant="destructive">
              <AlertDescription>
                {saveError === 'busy'
                  ? t('settings.sources.chunkErrors.busy')
                  : editing
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
        description={t('common.cantUndo')}
        modalState={deleteModalState}
        setModalState={setDeleteModalState}
        handleSubmit={handleConfirmedDelete}
        error={(reason) =>
          reason instanceof SourceBusy
            ? t('settings.sources.chunkErrors.busy')
            : t('settings.sources.chunkErrors.delete')
        }
        handleCancel={handleCancelDelete}
        submitLabel={t('modals.chunk.delete')}
        variant="destructive"
      />
    </div>
  );
};

/**
 * Above a flagged chunk in the reader: what the scan found and what agents
 * do with it, or, once it is marked safe, that agents treat it as clean, with
 * an Undo for whoever may edit the source.
 */
function InjectionNotice({
  injection,
  canUndo,
  busy,
  onUndo,
}: {
  injection: ChunkInjection;
  canUndo: boolean;
  busy: boolean;
  onUndo: () => void;
}) {
  const { t } = useTranslation();
  if (!injection.level) return null;
  if (injection.allowed)
    return (
      <Alert
        variant="info"
        role="status"
        className="mb-4"
        data-testid="chunk-injection-safe"
      >
        <AlertDescription>
          {t('settings.sources.injection.safeNotice')}{' '}
          {canUndo ? (
            <Button
              type="button"
              variant="link"
              size="text"
              tone="current"
              loading={busy}
              onClick={onUndo}
            >
              {t('settings.sources.injection.undo')}
            </Button>
          ) : null}
        </AlertDescription>
      </Alert>
    );
  return (
    <Alert variant="warning" className="mb-4" data-testid="chunk-injection">
      <AlertDescription>
        {t('settings.sources.injection.flaggedNotice', {
          percent: Math.round((injection.p ?? 0) * 100),
        })}
      </AlertDescription>
    </Alert>
  );
}

export default Chunks;
