import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import FileIcon from '../assets/file.svg';
import FolderIcon from '../assets/folder.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import NoFilesIcon from '../assets/no-files.svg';
import SearchIcon from '../assets/search.svg';
import {
  useDarkTheme,
  useLoaderState,
  useMediaQuery,
  useOutsideAlerter,
} from '../hooks';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { ChunkType } from '../settings/types';
import Pagination from './DocumentPagination';
import SkeletonLoader from './SkeletonLoader';

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

  const lineHeight = 19.93;
  const contentLines = value.split('\n').length;

  const heightOffset = isMobile ? 200 : 300;
  const minLinesForDisplay = Math.ceil(
    (typeof window !== 'undefined' ? window.innerHeight - heightOffset : 600) /
      lineHeight,
  );
  const totalLines = Math.max(contentLines, minLinesForDisplay);

  return (
    <div className={`relative w-full ${className}`}>
      <div
        className="pointer-events-none absolute top-0 left-0 w-8 pr-2 text-right font-mono text-xs leading-[19.93px] text-gray-500 select-none lg:w-12 lg:pr-3 lg:text-sm dark:text-gray-400"
        style={{
          height: `${totalLines * lineHeight}px`,
        }}
      >
        {Array.from({ length: totalLines }, (_, i) => (
          <div
            key={i + 1}
            className="flex h-[19.93px] items-center justify-end leading-[19.93px]"
          >
            {i + 1}
          </div>
        ))}
      </div>
      <textarea
        className={`text-foreground w-full resize-none overflow-hidden border-none bg-transparent pl-8 font-['Inter'] text-[13.68px] leading-[19.93px] outline-none lg:pl-12 dark:text-white ${isMobile ? 'min-h-[calc(100vh-200px)]' : 'min-h-[calc(100vh-300px)]'} ${!editable ? 'select-none' : ''}`}
        value={value}
        onChange={editable ? handleChange : undefined}
        onDoubleClick={onDoubleClick}
        placeholder={placeholder}
        aria-label={ariaLabel}
        rows={totalLines}
        readOnly={!editable}
        style={{
          height: `${totalLines * lineHeight}px`,
        }}
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
}

const Chunks: React.FC<ChunksProps> = ({
  documentId,
  documentName,
  handleGoBack,
  path,
  displayPath,
  onFileSearch,
  onFileSelect,
}) => {
  const [fileSearchQuery, setFileSearchQuery] = useState('');
  const [fileSearchResults, setFileSearchResults] = useState<SearchResult[]>(
    [],
  );
  const searchDropdownRef = useRef<HTMLDivElement>(null);
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [isDarkTheme] = useDarkTheme();
  const [paginatedChunks, setPaginatedChunks] = useState<ChunkType[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(5);
  const [totalChunks, setTotalChunks] = useState(0);
  const [loading, setLoading] = useLoaderState(true);
  const [searchTerm, setSearchTerm] = useState<string>('');
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
        searchTerm,
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
    const delayDebounceFn = setTimeout(() => {
      if (page !== 1) {
        setPage(1);
      } else {
        fetchChunks();
      }
    }, 300);

    return () => clearTimeout(delayDebounceFn);
  }, [searchTerm]);

  useEffect(() => {
    !loading && fetchChunks();
  }, [page, perPage, path]);

  useEffect(() => {
    setSearchTerm('');
    setPage(1);
  }, [path]);

  const filteredChunks = paginatedChunks;

  const renderPathNavigation = () => {
    return (
      <div className="mb-0 flex min-h-[38px] flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
        <div className="flex w-full items-center sm:w-auto">
          <button
            className="mr-3 flex h-[29px] w-[29px] items-center justify-center rounded-full border p-2 text-sm font-medium text-gray-400 transition-all duration-200 dark:border-0 dark:text-gray-500"
            onClick={
              editingChunk
                ? () => setEditingChunk(null)
                : isAddingChunk
                  ? () => setIsAddingChunk(false)
                  : handleGoBack
            }
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
          </button>

          <div className="flex flex-wrap items-center">
            {/* Removed the directory icon */}
            <span className="font-semibold wrap-break-word text-[#7D54D1]">
              {documentName}
            </span>

            {pathParts.length > 0 && (
              <>
                <span className="mx-1 shrink-0 text-gray-500">/</span>
                {pathParts.map((part, index) => (
                  <React.Fragment key={index}>
                    <span
                      className={`wrap-break-word ${
                        index < pathParts.length - 1
                          ? 'font-medium text-[#7D54D1]'
                          : 'text-gray-700 dark:text-gray-300'
                      }`}
                    >
                      {part}
                    </span>
                    {index < pathParts.length - 1 && (
                      <span className="mx-1 shrink-0 text-gray-500">/</span>
                    )}
                  </React.Fragment>
                ))}
              </>
            )}
          </div>
        </div>

        <div className="mt-2 flex w-full flex-row flex-nowrap items-center justify-end gap-2 overflow-x-auto sm:mt-0 sm:w-auto">
          {editingChunk ? (
            !isEditing ? (
              <>
                <button
                  className="bg-primary hover:bg-primary/90 flex h-[38px] min-w-[108px] items-center justify-center rounded-full px-4 text-[14px] font-medium whitespace-nowrap text-white"
                  onClick={() => setIsEditing(true)}
                >
                  {t('modals.chunk.edit')}
                </button>
                <button
                  className="flex h-[38px] min-w-[108px] items-center justify-center rounded-full border border-solid border-red-500 px-4 py-1 text-[14px] font-medium text-nowrap text-red-500 hover:bg-red-500 hover:text-white"
                  onClick={() => {
                    confirmDeleteChunk(editingChunk);
                  }}
                >
                  {t('modals.chunk.delete')}
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={() => {
                    setIsEditing(false);
                  }}
                  className="dark:text-foreground hover:bg-accent dark:hover:bg-accent flex h-[38px] min-w-[108px] cursor-pointer items-center justify-center rounded-full px-4 py-1 text-sm font-medium text-nowrap"
                >
                  {t('modals.chunk.cancel')}
                </button>
                <button
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
                    (editingTitle === (editingChunk?.metadata?.title || '') &&
                      editingText === (editingChunk?.text || ''))
                  }
                  className={`flex h-[38px] min-w-[108px] items-center justify-center rounded-full px-4 py-1 text-[14px] font-medium text-nowrap text-white transition-all ${
                    editingText.trim() &&
                    (editingTitle !== (editingChunk?.metadata?.title || '') ||
                      editingText !== (editingChunk?.text || ''))
                      ? 'bg-primary hover:bg-primary/90 cursor-pointer'
                      : 'cursor-not-allowed bg-gray-400'
                  }`}
                >
                  {t('modals.chunk.save')}
                </button>
              </>
            )
          ) : isAddingChunk ? (
            <>
              <button
                onClick={() => setIsAddingChunk(false)}
                className="dark:text-foreground hover:bg-accent dark:hover:bg-accent flex h-[38px] min-w-[108px] cursor-pointer items-center justify-center rounded-full px-4 py-1 text-sm font-medium text-nowrap"
              >
                {t('modals.chunk.cancel')}
              </button>
              <button
                onClick={() => {
                  if (editingText.trim()) {
                    handleAddChunk(editingTitle, editingText);
                    setIsAddingChunk(false);
                  }
                }}
                disabled={!editingText.trim()}
                className={`flex h-[38px] min-w-[108px] items-center justify-center rounded-full px-4 py-1 text-[14px] font-medium text-nowrap text-white transition-all ${
                  editingText.trim()
                    ? 'bg-primary hover:bg-primary/90 cursor-pointer'
                    : 'cursor-not-allowed bg-gray-400'
                }`}
              >
                {t('modals.chunk.add')}
              </button>
            </>
          ) : null}
        </div>
      </div>
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
        <div className="relative flex items-center">
          <div className="pointer-events-none absolute left-3">
            <img src={SearchIcon} alt="Search" className="h-4 w-4" />
          </div>
          <input
            type="text"
            value={fileSearchQuery}
            onChange={(e) => handleFileSearchChange(e.target.value)}
            placeholder={t('settings.sources.searchFiles')}
            className={`border-border dark:border-border h-[38px] w-full border py-2 pr-4 pl-10 ${
              fileSearchQuery ? 'rounded-t-[6px]' : 'rounded-[6px]'
            } bg-transparent transition-all duration-200 focus:outline-none`}
          />
        </div>

        {fileSearchQuery && (
          <div className="border-border bg-card dark:border-border dark:bg-card absolute z-10 max-h-[calc(100vh-200px)] w-full overflow-hidden rounded-b-[6px] border border-t-0 shadow-lg">
            <div className="max-h-[calc(100vh-200px)] overflow-x-hidden overflow-y-auto">
              {fileSearchResults.length === 0 ? (
                <div className="py-2 text-center text-sm text-gray-500 dark:text-gray-400">
                  {t('settings.sources.noResults')}
                </div>
              ) : (
                fileSearchResults.map((result, index) => (
                  <div
                    key={index}
                    title={result.path}
                    onClick={() => handleSearchResultClick(result)}
                    className={`hover:bg-muted dark:hover:bg-muted flex cursor-pointer items-center px-3 py-2 ${
                      index !== fileSearchResults.length - 1
                        ? 'border-border dark:border-border border-b'
                        : ''
                    }`}
                  >
                    <img
                      src={result.isFile ? FileIcon : FolderIcon}
                      alt={result.isFile ? 'File' : 'Folder'}
                      className="mr-2 h-4 w-4 shrink-0"
                    />
                    <span className="truncate text-sm">
                      {result.name ||
                        result.path.split('/').pop() ||
                        result.path}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
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
                <div className="border-border dark:border-border flex h-[38px] w-full flex-1 items-center overflow-hidden rounded-md border">
                  <div className="flex h-full items-center px-4 font-medium whitespace-nowrap text-gray-700">
                    {totalChunks > 999999
                      ? `${(totalChunks / 1000000).toFixed(2)}M`
                      : totalChunks > 999
                        ? `${(totalChunks / 1000).toFixed(2)}K`
                        : totalChunks}{' '}
                    {t('settings.sources.chunks')}
                  </div>
                  <div className="bg-border dark:bg-border h-full w-px"></div>
                  <div className="h-full flex-1">
                    <input
                      type="text"
                      placeholder={t('settings.sources.searchPlaceholder')}
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="h-full w-full border-none bg-transparent px-3 py-2 text-[13.56px] leading-[100%] font-normal outline-none"
                    />
                  </div>
                </div>
                <button
                  className="bg-primary hover:bg-primary/90 flex h-[38px] w-full min-w-[108px] shrink-0 items-center justify-center rounded-full px-4 text-[14px] font-medium whitespace-normal text-white sm:w-auto"
                  title={t('settings.sources.addChunk')}
                  onClick={() => {
                    setIsAddingChunk(true);
                    setEditingTitle('');
                    setEditingText('');
                  }}
                >
                  {t('settings.sources.addChunk')}
                </button>
              </div>
              {loading ? (
                <div className="grid w-full grid-cols-1 justify-items-start gap-4 sm:grid-cols-[repeat(auto-fit,minmax(400px,1fr))]">
                  <SkeletonLoader component="chunkCards" count={perPage} />
                </div>
              ) : (
                <div className="grid w-full grid-cols-1 justify-items-start gap-4 sm:grid-cols-[repeat(auto-fit,minmax(400px,1fr))]">
                  {filteredChunks.length === 0 ? (
                    <div className="col-span-full flex min-h-[50vh] w-full flex-col items-center justify-center text-center text-gray-500 dark:text-gray-400">
                      <img
                        src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                        alt={t('settings.sources.noChunksAlt')}
                        className="mx-auto mb-2 h-24 w-24"
                      />
                      {t('settings.sources.noChunks')}
                    </div>
                  ) : (
                    filteredChunks.map((chunk, index) => (
                      <div
                        key={index}
                        className="border-border dark:border-border relative flex h-[197px] w-full max-w-[487px] transform cursor-pointer flex-col justify-between overflow-hidden rounded-[5.86px] border transition-transform duration-200 hover:scale-105"
                        onClick={() => {
                          setEditingChunk(chunk);
                          setEditingTitle(chunk.metadata?.title || '');
                          setEditingText(chunk.text || '');
                        }}
                      >
                        <div className="w-full">
                          <div className="border-border bg-muted dark:border-border dark:bg-card flex w-full items-center justify-between border-b px-4 py-3">
                            <div className="text-sm text-[#59636E]">
                              {chunk.metadata.token_count
                                ? chunk.metadata.token_count.toLocaleString()
                                : '-'}{' '}
                              {t('settings.sources.tokensUnit')}
                            </div>
                          </div>
                          <div className="px-4 pt-3 pb-6">
                            <p className="text-foreground line-clamp-6 font-['Inter'] text-[13.68px] leading-[19.93px] font-normal">
                              {chunk.text}
                            </p>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}
            </>
          ) : isAddingChunk ? (
            <div className="w-full">
              <div className="border-border dark:border-border relative overflow-hidden rounded-lg border">
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
                <div className="border-border dark:border-border relative flex w-full flex-col overflow-hidden rounded-[5.86px] border">
                  <div className="border-border bg-muted dark:border-border dark:bg-card flex w-full items-center justify-between border-b px-4 py-3">
                    <div className="text-sm text-[#59636E]">
                      {editingChunk.metadata.token_count
                        ? editingChunk.metadata.token_count.toLocaleString()
                        : '-'}{' '}
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
                currentPage={page}
                totalPages={Math.ceil(totalChunks / perPage)}
                rowsPerPage={perPage}
                onPageChange={setPage}
                onRowsPerPageChange={(rows) => {
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
        variant="danger"
      />
    </div>
  );
};

export default Chunks;
