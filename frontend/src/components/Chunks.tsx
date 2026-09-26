import { File, Folder } from 'lucide-react';
import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { cn, fieldFrame } from '@/lib/utils';

import userService from '../api/services/userService';
import {
  useDebouncedValue,
  useLoaderState,
  useMediaQuery,
  useOutsideAlerter,
} from '../hooks';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { ChunkType } from '../settings/types';
import { formatChunkTokens } from './chunkUtils';
import SkeletonLoader from './SkeletonLoader';
import PathHeader from './tree/PathHeader';
import { Button } from './ui/button';
import { Card } from './ui/card';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from './ui/command';
import { EmptyState } from './ui/empty-state';
import { Input } from './ui/input';
import { Pagination } from './ui/pagination';

// The search field's frame: the Input look around a CommandInput (38px,
// rounded-md, focus ring while the input has keyboard focus). CommandInput's
// row is 36px with a bottom rule; pt-px + overflow-hidden clips that rule.
const SEARCH_FRAME = cn(
  fieldFrame,
  'border-border has-[input:focus-visible]:border-ring has-[input:focus-visible]:ring-ring/50 h-9.5 overflow-hidden rounded-md pt-px has-[input:focus-visible]:ring-3',
);

interface LineNumberedTextareaProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  className?: string;
  editable?: boolean;
  onDoubleClick?: () => void;
}

const LineNumberedTextarea: React.FC<LineNumberedTextareaProps> = ({
  value,
  onChange,
  placeholder,
  ariaLabel,
  className = '',
  editable = true,
  onDoubleClick,
}) => {
  const { isMobile } = useMediaQuery();

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onChange(e.target.value);
  };

  const lineHeight = 20;
  const contentLines = value.split('\n').length;

  const heightOffset = isMobile ? 200 : 300;
  const minLinesForDisplay = Math.ceil(
    (typeof window !== 'undefined' ? window.innerHeight - heightOffset : 600) /
      lineHeight,
  );
  const totalLines = Math.max(contentLines, minLinesForDisplay);

  return (
    <div
      className={cn('relative w-full', className)}
      style={
        {
          '--numbered-height': `${totalLines * lineHeight}px`,
        } as React.CSSProperties
      }
    >
      <div className="text-muted-foreground pointer-events-none absolute top-0 left-0 h-(--numbered-height) w-8 pr-2 text-right font-mono text-xs leading-5 select-none lg:w-12 lg:pr-3 lg:text-sm">
        {Array.from({ length: totalLines }, (_, i) => (
          <div
            key={i + 1}
            className="flex h-5 items-center justify-end leading-5"
          >
            {i + 1}
          </div>
        ))}
      </div>
      <textarea
        className={cn(
          'text-foreground focus-visible:ring-ring/50 focus-visible:border-ring h-(--numbered-height) w-full resize-none overflow-hidden border-none bg-transparent pl-8 text-sm leading-5 outline-none focus-visible:ring-3 lg:pl-12',
          isMobile
            ? 'min-h-[calc(100svh-200px)]'
            : 'min-h-[calc(100svh-300px)]',
          !editable && 'select-none',
        )}
        value={value}
        onChange={editable ? handleChange : undefined}
        onDoubleClick={onDoubleClick}
        placeholder={placeholder}
        aria-label={ariaLabel}
        rows={totalLines}
        readOnly={!editable}
      />
    </div>
  );
};

interface SearchResult {
  path: string;
  isFile: boolean;
  name?: string;
}

interface ChunksProps {
  documentId: string;
  documentName?: string;
  handleGoBack: () => void;
  path?: string;
  displayPath?: string;
  onFileSearch?: (query: string) => SearchResult[];
  onFileSelect?: (path: string) => void;
  /** Extra header control, rendered left of the chunk actions. */
  headerAction?: React.ReactNode;
  /**
   * Opens a level of the path: 0 is the source root, n the folder made of
   * the first n path segments. Without it the root crumb calls handleGoBack
   * and folder crumbs are plain text.
   */
  onPathSelect?: (depth: number) => void;
}

const Chunks: React.FC<ChunksProps> = ({
  documentId,
  documentName,
  handleGoBack,
  path,
  displayPath,
  onFileSearch,
  onFileSelect,
  headerAction,
  onPathSelect,
}) => {
  const [fileSearchQuery, setFileSearchQuery] = useState('');
  const [fileSearchResults, setFileSearchResults] = useState<SearchResult[]>(
    [],
  );
  const searchDropdownRef = useRef<HTMLDivElement>(null);
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [paginatedChunks, setPaginatedChunks] = useState<ChunkType[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(5);
  const [totalChunks, setTotalChunks] = useState(0);
  const [loading, setLoading] = useLoaderState(true);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const debouncedSearchTerm = useDebouncedValue(searchTerm, 300);
  const [editingChunk, setEditingChunk] = useState<ChunkType | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [editingText, setEditingText] = useState('');
  const [isAddingChunk, setIsAddingChunk] = useState(false);
  const [deleteModalState, setDeleteModalState] =
    useState<ActiveState>('INACTIVE');
  const [chunkToDelete, setChunkToDelete] = useState<ChunkType | null>(null);
  const [isEditing, setIsEditing] = useState(false);

  const displayPathValue = displayPath ?? path ?? '';
  const pathParts = displayPathValue ? displayPathValue.split('/') : [];

  const fetchChunks = async () => {
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

      setPage(data.page);
      setPerPage(data.per_page);
      setTotalChunks(data.total);
      setPaginatedChunks(data.chunks);
    } catch (error) {
      setPaginatedChunks([]);
      console.error(error);
    } finally {
      // ✅ always runs, success or failure
      setLoading(false);
    }
  };

  const handleAddChunk = (title: string, text: string) => {
    if (!text.trim()) {
      return;
    }

    try {
      const metadata = {
        source: path || documentName,
        source_id: documentId,
        title: title,
      };

      userService
        .addChunk(
          {
            id: documentId,
            text: text,
            metadata: metadata,
          },
          token,
        )
        .then((response) => {
          if (!response.ok) {
            throw new Error('Failed to add chunk');
          }
          fetchChunks();
        });
    } catch (e) {
      console.log(e);
    }
  };

  const handleUpdateChunk = (title: string, text: string, chunk: ChunkType) => {
    if (!text.trim()) {
      return;
    }

    const originalTitle = chunk.metadata?.title || '';
    const originalText = chunk.text || '';

    if (title === originalTitle && text === originalText) {
      return;
    }

    try {
      userService
        .updateChunk(
          {
            id: documentId,
            chunk_id: chunk.doc_id,
            text: text,
            metadata: {
              title: title,
            },
          },
          token,
        )
        .then((response) => {
          if (!response.ok) {
            throw new Error('Failed to update chunk');
          }
          fetchChunks();
        });
    } catch (e) {
      console.log(e);
    }
  };

  const handleDeleteChunk = (chunk: ChunkType) => {
    try {
      userService
        .deleteChunk(documentId, chunk.doc_id, token)
        .then((response) => {
          if (!response.ok) {
            throw new Error('Failed to delete chunk');
          }
          setEditingChunk(null);
          fetchChunks();
        });
    } catch (e) {
      console.log(e);
    }
  };

  const confirmDeleteChunk = (chunk: ChunkType) => {
    setChunkToDelete(chunk);
    setDeleteModalState('ACTIVE');
  };

  const handleConfirmedDelete = () => {
    if (chunkToDelete) {
      handleDeleteChunk(chunkToDelete);
      setDeleteModalState('INACTIVE');
      setChunkToDelete(null);
    }
  };

  const handleCancelDelete = () => {
    setDeleteModalState('INACTIVE');
    setChunkToDelete(null);
  };

  useEffect(() => {
    if (page !== 1) {
      setPage(1);
    } else {
      fetchChunks();
    }
  }, [debouncedSearchTerm]);

  useEffect(() => {
    !loading && fetchChunks();
  }, [page, perPage, path]);

  useEffect(() => {
    setSearchTerm('');
    setPage(1);
  }, [path]);

  const filteredChunks = paginatedChunks;

  // The root crumb returns to the source (TreeBrowser: its top folder;
  // standalone: back to the source list). Folder crumbs only navigate when
  // the parent can open a folder (onPathSelect); the file is the current one.
  const renderPathNavigation = () => {
    const rootLabel = documentName ?? '';
    const selectRoot = onPathSelect ? () => onPathSelect(0) : handleGoBack;
    return (
      <PathHeader
        root={{
          label: rootLabel,
          onSelect: pathParts.length > 0 ? selectRoot : undefined,
        }}
        segments={pathParts.map((part, index) => ({
          label: part,
          onSelect:
            onPathSelect && index < pathParts.length - 1
              ? () => onPathSelect(index + 1)
              : undefined,
        }))}
        backLabel={t('settings.sources.back')}
        onBack={
          editingChunk
            ? () => setEditingChunk(null)
            : isAddingChunk
              ? () => setIsAddingChunk(false)
              : handleGoBack
        }
        actions={
          headerAction || editingChunk || isAddingChunk ? (
            <>
              {headerAction}
              {editingChunk ? (
                !isEditing ? (
                  <>
                    <Button
                      type="button"
                      size="field"
                      shape="pill"
                      onClick={() => setIsEditing(true)}
                    >
                      {t('modals.chunk.edit')}
                    </Button>
                    <Button
                      type="button"
                      variant="destructive-outline"
                      size="field"
                      shape="pill"
                      onClick={() => {
                        confirmDeleteChunk(editingChunk);
                      }}
                    >
                      {t('modals.chunk.delete')}
                    </Button>
                  </>
                ) : (
                  <>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => {
                        setIsEditing(false);
                      }}
                      size="field"
                      shape="pill"
                    >
                      {t('modals.chunk.cancel')}
                    </Button>
                    <Button
                      type="button"
                      onClick={() => {
                        if (editingText.trim()) {
                          const hasChanges =
                            editingTitle !==
                              (editingChunk?.metadata?.title || '') ||
                            editingText !== (editingChunk?.text || '');

                          if (hasChanges) {
                            handleUpdateChunk(
                              editingTitle,
                              editingText,
                              editingChunk,
                            );
                          }
                          setIsEditing(false);
                          setEditingChunk(null);
                        }
                      }}
                      disabled={
                        !editingText.trim() ||
                        (editingTitle ===
                          (editingChunk?.metadata?.title || '') &&
                          editingText === (editingChunk?.text || ''))
                      }
                      size="field"
                      shape="pill"
                    >
                      {t('modals.chunk.save')}
                    </Button>
                  </>
                )
              ) : isAddingChunk ? (
                <>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setIsAddingChunk(false)}
                    size="field"
                    shape="pill"
                  >
                    {t('modals.chunk.cancel')}
                  </Button>
                  <Button
                    type="button"
                    onClick={() => {
                      if (editingText.trim()) {
                        handleAddChunk(editingTitle, editingText);
                        setIsAddingChunk(false);
                      }
                    }}
                    disabled={!editingText.trim()}
                    size="field"
                    shape="pill"
                  >
                    {t('modals.chunk.add')}
                  </Button>
                </>
              ) : null}
            </>
          ) : undefined
        }
      />
    );
  };

  // File search handling
  const handleFileSearchChange = (query: string) => {
    setFileSearchQuery(query);
    if (query.trim() && onFileSearch) {
      const results = onFileSearch(query);
      setFileSearchResults(results);
    } else {
      setFileSearchResults([]);
    }
  };

  const handleSearchResultClick = (result: SearchResult) => {
    if (!onFileSelect) return;

    if (result.isFile) {
      onFileSelect(result.path);
    } else {
      // For directories, navigate to the directory and return to file tree
      onFileSelect(result.path);
      handleGoBack();
    }
    setFileSearchQuery('');
    setFileSearchResults([]);
  };

  useOutsideAlerter(
    searchDropdownRef,
    () => {
      setFileSearchQuery('');
      setFileSearchResults([]);
    },
    [], // No additional dependencies
    false, // Don't handle escape key
  );

  const renderFileSearch = () => {
    return (
      <div className="relative" ref={searchDropdownRef}>
        {/* `contents`: the Command only scopes cmdk (the arrow keys move from
            the input to the rows); the frame and the dropdown draw the look. */}
        <Command shouldFilter={false} className="contents">
          <div className={SEARCH_FRAME}>
            <CommandInput
              value={fileSearchQuery}
              onValueChange={handleFileSearchChange}
              placeholder={t('settings.sources.searchFiles')}
            />
          </div>

          {fileSearchQuery && (
            <div className="border-border bg-popover text-popover-foreground absolute top-full right-0 left-0 z-20 mt-1 w-full overflow-hidden rounded-xl border shadow-md">
              <CommandList className="max-h-[calc(100dvh-200px)]">
                {fileSearchResults.length === 0 ? (
                  <CommandEmpty>{t('settings.sources.noResults')}</CommandEmpty>
                ) : (
                  <CommandGroup>
                    {fileSearchResults.map((result) => (
                      <CommandItem
                        key={result.path}
                        value={result.path}
                        title={result.path}
                        onSelect={() => handleSearchResultClick(result)}
                      >
                        {result.isFile ? (
                          <File />
                        ) : (
                          <Folder className="text-primary" />
                        )}
                        <span className="truncate">
                          {result.name ||
                            result.path.split('/').pop() ||
                            result.path}
                        </span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                )}
              </CommandList>
            </div>
          )}
        </Command>
      </div>
    );
  };

  return (
    <div className="flex flex-col">
      <div className="mb-2">{renderPathNavigation()}</div>
      <div className="flex gap-4">
        {onFileSearch && onFileSelect && (
          <div className="hidden w-[198px] lg:block">{renderFileSearch()}</div>
        )}

        {/* Right side: Chunks content */}
        <div className="flex-1">
          {!editingChunk && !isAddingChunk ? (
            <>
              <div className="mb-3 flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
                <div className="border-border flex h-9.5 w-full flex-1 items-center overflow-hidden rounded-md border">
                  <div className="text-foreground flex h-full items-center px-4 font-medium whitespace-nowrap">
                    {totalChunks > 999999
                      ? `${(totalChunks / 1000000).toFixed(2)}M`
                      : totalChunks > 999
                        ? `${(totalChunks / 1000).toFixed(2)}K`
                        : totalChunks}{' '}
                    {t('settings.sources.chunks')}
                  </div>
                  <div className="bg-border h-full w-px"></div>
                  <div className="h-full flex-1 px-3 py-2">
                    <Input
                      type="text"
                      variant="bare"
                      placeholder={t('settings.sources.searchPlaceholder')}
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="h-full"
                    />
                  </div>
                </div>
                <Button
                  type="button"
                  size="field"
                  shape="pill"
                  className="w-full shrink-0 sm:w-auto"
                  onClick={() => {
                    setIsAddingChunk(true);
                    setEditingTitle('');
                    setEditingText('');
                  }}
                >
                  {t('settings.sources.addChunk')}
                </Button>
              </div>
              {loading ? (
                <div className="grid w-full grid-cols-1 justify-items-start gap-4 sm:grid-cols-[repeat(auto-fit,minmax(400px,1fr))]">
                  <SkeletonLoader component="chunkCards" count={perPage} />
                </div>
              ) : (
                <div className="grid w-full grid-cols-1 justify-items-start gap-4 sm:grid-cols-[repeat(auto-fit,minmax(400px,1fr))]">
                  {filteredChunks.length === 0 ? (
                    <EmptyState
                      size="sm"
                      title={t('settings.sources.noChunks')}
                      className="col-span-full min-h-[50svh] w-full"
                    />
                  ) : (
                    filteredChunks.map((chunk, index) => (
                      <Card
                        key={index}
                        interactive
                        padding="none"
                        asChild
                        className="relative h-[197px] w-full max-w-[487px] justify-between gap-0 overflow-hidden"
                      >
                        <button
                          type="button"
                          onClick={() => {
                            setEditingChunk(chunk);
                            setEditingTitle(chunk.metadata?.title || '');
                            setEditingText(chunk.text || '');
                          }}
                        >
                          <div className="w-full">
                            <div className="border-border bg-muted flex w-full items-center justify-between border-b px-4 py-3">
                              <div className="text-muted-foreground text-sm">
                                {formatChunkTokens(chunk.metadata)}{' '}
                                {t('settings.sources.tokensUnit')}
                              </div>
                            </div>
                            <div className="px-4 pt-3 pb-6">
                              <p className="text-foreground line-clamp-6 text-sm leading-5 font-normal">
                                {chunk.text}
                              </p>
                            </div>
                          </div>
                        </button>
                      </Card>
                    ))
                  )}
                </div>
              )}
            </>
          ) : isAddingChunk ? (
            <div className="w-full">
              <div className="border-border relative overflow-hidden rounded-lg border">
                <LineNumberedTextarea
                  value={editingText}
                  onChange={setEditingText}
                  ariaLabel={t('modals.chunk.promptText')}
                  editable={true}
                />
              </div>
            </div>
          ) : (
            editingChunk && (
              <div className="w-full">
                <div className="border-border relative flex w-full flex-col overflow-hidden rounded-md border">
                  <div className="border-border bg-muted flex w-full items-center justify-between border-b px-4 py-3">
                    <div className="text-muted-foreground text-sm">
                      {formatChunkTokens(editingChunk.metadata)}{' '}
                      {t('settings.sources.tokensUnit')}
                    </div>
                  </div>
                  <div className="overflow-hidden p-4">
                    <LineNumberedTextarea
                      value={isEditing ? editingText : editingChunk.text}
                      onChange={setEditingText}
                      ariaLabel={t('modals.chunk.promptText')}
                      editable={isEditing}
                      onDoubleClick={() => {
                        if (!isEditing) {
                          setIsEditing(true);
                          setEditingTitle(editingChunk.metadata.title || '');
                          setEditingText(editingChunk.text);
                        }
                      }}
                    />
                  </div>
                </div>
              </div>
            )
          )}

          {!loading &&
            totalChunks > perPage &&
            !editingChunk &&
            !isAddingChunk && (
              <Pagination
                page={page}
                pageCount={Math.ceil(totalChunks / perPage)}
                pageSize={perPage}
                onPageChange={setPage}
                onPageSizeChange={(rows) => {
                  setPerPage(rows);
                  setPage(1);
                }}
              />
            )}
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      <ConfirmationModal
        message={t('modals.chunk.deleteConfirmation')}
        modalState={deleteModalState}
        setModalState={setDeleteModalState}
        handleSubmit={handleConfirmedDelete}
        handleCancel={handleCancelDelete}
        submitLabel={t('modals.chunk.delete')}
        variant="destructive"
      />
    </div>
  );
};

export default Chunks;
