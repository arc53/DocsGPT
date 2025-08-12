import React, { useState, useEffect, useRef } from 'react';
import { useSelector } from 'react-redux';
import { useTranslation } from 'react-i18next';
import { selectToken } from '../preferences/preferenceSlice';
import { useDarkTheme, useLoaderState, useMediaQuery, useOutsideAlerter } from '../hooks';
import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import NoFilesIcon from '../assets/no-files.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import OutlineSource from '../assets/outline-source.svg';
import SkeletonLoader from './SkeletonLoader';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { ChunkType } from '../settings/types';
import Pagination from './DocumentPagination';
import FileIcon from '../assets/file.svg';
import FolderIcon from '../assets/folder.svg';
import SearchIcon from '../assets/search.svg';
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
  onDoubleClick
}) => {
  const { isMobile } = useMediaQuery();

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onChange(e.target.value);
  };

  const lineHeight = 19.93;
  const contentLines = value.split('\n').length;

  const heightOffset = isMobile ? 200 : 300;
  const minLinesForDisplay = Math.ceil((typeof window !== 'undefined' ? window.innerHeight - heightOffset : 600) / lineHeight);
  const totalLines = Math.max(contentLines, minLinesForDisplay);

  return (
    <div className={`relative w-full ${className}`}>
      <div
        className="absolute left-0 top-0 w-8 lg:w-12 text-right text-gray-500 dark:text-gray-400 text-xs lg:text-sm font-mono leading-[19.93px] select-none pr-2 lg:pr-3 pointer-events-none"
        style={{
          height: `${totalLines * lineHeight}px`
        }}
      >
        {Array.from({ length: totalLines }, (_, i) => (
          <div
            key={i + 1}
            className="flex items-center justify-end h-[19.93px] leading-[19.93px]"
          >
            {i + 1}
          </div>
        ))}
      </div>
      <textarea
        className={`w-full resize-none bg-transparent dark:text-white font-['Inter'] text-[13.68px] leading-[19.93px] text-[#18181B] outline-none border-none pl-8 lg:pl-12 overflow-hidden ${isMobile ? 'min-h-[calc(100vh-200px)]' : 'min-h-[calc(100vh-300px)]'} ${!editable ? 'select-none' : ''}`}
        value={value}
        onChange={editable ? handleChange : undefined}
        onDoubleClick={onDoubleClick}
        placeholder={placeholder}
        aria-label={ariaLabel}
        rows={totalLines}
        readOnly={!editable}
        style={{
          height: `${totalLines * lineHeight}px`
        }}
      />
    </div>
  );
};

interface SearchResult {
  path: string;
  isFile: boolean;
}

interface ChunksProps {
  documentId: string;
  documentName?: string;
  handleGoBack: () => void;
  path?: string;
  onFileSearch?: (query: string) => SearchResult[];
  onFileSelect?: (path: string) => void;
}

const Chunks: React.FC<ChunksProps> = ({
  documentId,
  documentName,
  handleGoBack,
  path,
  onFileSearch,
  onFileSelect,
}) => {
  const [fileSearchQuery, setFileSearchQuery] = useState('');
  const [fileSearchResults, setFileSearchResults] = useState<SearchResult[]>([]);
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
  const [deleteModalState, setDeleteModalState] = useState<ActiveState>('INACTIVE');
  const [chunkToDelete, setChunkToDelete] = useState<ChunkType | null>(null);
  const [isEditing, setIsEditing] = useState(false);

  const pathParts = path ? path.split('/') : [];

  const fetchChunks = () => {
    setLoading(true);
    try {
      userService
        .getDocumentChunks(documentId, page, perPage, token, path, searchTerm)
        .then((response) => {
          if (!response.ok) {
            setLoading(false);
            setPaginatedChunks([]);
            throw new Error('Failed to fetch chunks data');
          }
          return response.json();
        })
        .then((data) => {
          setPage(data.page);
          setPerPage(data.per_page);
          setTotalChunks(data.total);
          setPaginatedChunks(data.chunks);
          setLoading(false);
        })
        .catch((error) => {
          setLoading(false);
          setPaginatedChunks([]);
        });
    } catch (e) {
      setLoading(false);
      setPaginatedChunks([]);
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
      <div className="mb-0 min-h-[38px] flex flex-col sm:flex-row sm:items-center sm:justify-between text-base gap-2">
        <div className="flex w-full items-center sm:w-auto">
          <button
            className="mr-3 flex h-[29px] w-[29px] items-center justify-center rounded-full border p-2 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34] transition-all duration-200 font-medium"
            onClick={editingChunk ? () => setEditingChunk(null) : isAddingChunk ? () => setIsAddingChunk(false) : handleGoBack}
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
          </button>

          <div className="flex items-center flex-wrap">
            {/* Removed the directory icon */}
            <span className="text-[#7D54D1] font-semibold break-words">
              {documentName}
            </span>

            {pathParts.length > 0 && (
              <>
                <span className="mx-1 text-gray-500 flex-shrink-0">/</span>
                {pathParts.map((part, index) => (
                  <React.Fragment key={index}>
                    <span className={`break-words ${
                      index < pathParts.length - 1 
                        ? 'text-[#7D54D1] font-medium' 
                        : 'text-gray-700 dark:text-gray-300'
                    }`}>
                      {part}
                    </span>
                    {index < pathParts.length - 1 && (
                      <span className="mx-1 text-gray-500 flex-shrink-0">/</span>
                    )}
                  </React.Fragment>
                ))}
              </>
            )}
          </div>
        </div>

        <div className="flex flex-row flex-nowrap items-center gap-2 w-full sm:w-auto justify-end mt-2 sm:mt-0 overflow-x-auto">
          {editingChunk ? (
            !isEditing ? (
              <>
                <button
                  className="bg-purple-30 hover:bg-violets-are-blue flex h-[38px] min-w-[108px] items-center justify-center rounded-full px-4 text-[14px] whitespace-nowrap text-white font-medium"
                  onClick={() => setIsEditing(true)}
                >
                  {t('modals.chunk.edit')}
                </button>
                <button
                  className="rounded-full border border-solid border-red-500 px-4 py-1 text-[14px] text-nowrap text-red-500 hover:bg-red-500 hover:text-white h-[38px] min-w-[108px] flex items-center justify-center font-medium"
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
                  className="dark:text-light-gray cursor-pointer rounded-full px-4 py-1 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:hover:bg-[#767183]/50 text-nowrap h-[38px] min-w-[108px] flex items-center justify-center"
                >
                  {t('modals.chunk.cancel')}
                </button>
                <button
                  onClick={() => {
                    if (editingText.trim()) {
                      const hasChanges = editingTitle !== (editingChunk?.metadata?.title || '') ||
                                       editingText !== (editingChunk?.text || '');

                      if (hasChanges) {
                        handleUpdateChunk(editingTitle, editingText, editingChunk);
                      }
                      setIsEditing(false);
                      setEditingChunk(null);
                    }
                  }}
                  disabled={!editingText.trim() || (editingTitle === (editingChunk?.metadata?.title || '') && editingText === (editingChunk?.text || ''))}
                  className={`text-nowrap rounded-full px-4 py-1 text-[14px] text-white transition-all flex items-center justify-center h-[38px] min-w-[108px] font-medium ${
                    editingText.trim() && (editingTitle !== (editingChunk?.metadata?.title || '') || editingText !== (editingChunk?.text || ''))
                      ? 'bg-purple-30 hover:bg-violets-are-blue cursor-pointer'
                      : 'bg-gray-400 cursor-not-allowed'
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
                className="dark:text-light-gray cursor-pointer rounded-full px-4 py-1 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:hover:bg-[#767183]/50 text-nowrap h-[38px] min-w-[108px] flex items-center justify-center"
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
                className={`text-nowrap rounded-full px-4 py-1 text-[14px] text-white transition-all flex items-center justify-center h-[38px] min-w-[108px] font-medium ${
                  editingText.trim()
                    ? 'bg-purple-30 hover:bg-violets-are-blue cursor-pointer'
                    : 'bg-gray-400 cursor-not-allowed'
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
    false // Don't handle escape key
  );

  const renderFileSearch = () => {
    return (
      <div className="relative" ref={searchDropdownRef}>
        <div className="relative flex items-center">
          <div className="absolute left-3 pointer-events-none">
            <img src={SearchIcon} alt="Search" className="w-4 h-4" />
          </div>
          <input
            type="text"
            value={fileSearchQuery}
            onChange={(e) => handleFileSearchChange(e.target.value)}
            placeholder={t('settings.sources.searchFiles')}
            className={`w-full h-[38px] border border-[#D1D9E0] pl-10 pr-4 py-2 dark:border-[#6A6A6A] 
              ${fileSearchQuery 
                ? 'rounded-t-[6px]' 
                : 'rounded-[6px]'
              } 
              bg-transparent focus:outline-none dark:text-[#E0E0E0] transition-all duration-200`}
          />
        </div>

        {fileSearchQuery && (
          <div className="absolute z-10 max-h-[calc(100vh-200px)] w-full overflow-y-auto rounded-b-[6px] border border-t-0 border-[#D1D9E0] bg-white shadow-lg dark:border-[#6A6A6A] dark:bg-[#1F2023]">
            {fileSearchResults.length === 0 ? (
              <div className="py-2 text-center text-sm text-gray-500 dark:text-gray-400">
                {t('settings.sources.noResults')}
              </div>
            ) : (
              fileSearchResults.map((result, index) => (
                <div
                  key={index}
                  onClick={() => handleSearchResultClick(result)}
                  className={`flex cursor-pointer items-center px-3 py-2 hover:bg-[#ECEEEF] dark:hover:bg-[#27282D] ${
                    index !== fileSearchResults.length - 1
                      ? 'border-b border-[#D1D9E0] dark:border-[#6A6A6A]'
                      : ''
                  }`}
                >
                  <img
                    src={result.isFile ? FileIcon : FolderIcon}
                    alt={result.isFile ? 'File' : 'Folder'}
                    className="mr-2 h-4 w-4 flex-shrink-0"
                  />
                  <span className="text-sm dark:text-[#E0E0E0]">
                    {result.path.split('/').pop() || result.path}
                  </span>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="flex flex-col">
      <div className="mb-2">
        {renderPathNavigation()}
      </div>
      <div className="flex gap-4">
        {onFileSearch && onFileSelect && (
          <div className="hidden lg:block w-[198px]">
            {renderFileSearch()}
          </div>
        )}

        {/* Right side: Chunks content */}
        <div className="flex-1">
          {!editingChunk && !isAddingChunk ? (
            <>
              <div className="mb-3 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                <div className="flex-1 w-full flex items-center border border-[#D1D9E0] dark:border-[#6A6A6A] rounded-md overflow-hidden h-[38px]">
                  <div className="px-4 flex items-center text-gray-700 dark:text-[#E0E0E0] font-medium whitespace-nowrap h-full">
                    {totalChunks > 999999
                      ? `${(totalChunks / 1000000).toFixed(2)}M`
                      : totalChunks > 999
                        ? `${(totalChunks / 1000).toFixed(2)}K`
                        : totalChunks} {t('settings.sources.chunks')}
                  </div>
                  <div className="h-full w-[1px] bg-[#D1D9E0] dark:bg-[#6A6A6A]"></div>
                  <div className="flex-1 h-full">
                    <input
                      type="text"
                      placeholder={t('settings.sources.searchPlaceholder')}
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="w-full h-full px-3 py-2 bg-transparent border-none outline-none font-normal text-[13.56px] leading-[100%] dark:text-[#E0E0E0]"
                    />
                  </div>
                </div>
                <button
                  className="bg-purple-30 hover:bg-violets-are-blue flex h-[38px] w-full sm:w-auto min-w-[108px] items-center justify-center rounded-full px-4 text-[14px] whitespace-normal text-white shrink-0 font-medium"
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
                <div className="w-full grid grid-cols-1 sm:[grid-template-columns:repeat(auto-fit,minmax(400px,1fr))] gap-4 justify-items-start">
                  <SkeletonLoader component="chunkCards" count={perPage} />
                </div>
              ) : (
                <div className="w-full grid grid-cols-1 sm:[grid-template-columns:repeat(auto-fit,minmax(400px,1fr))] gap-4 justify-items-start">
                  {filteredChunks.length === 0 ? (
                    <div className="col-span-full w-full min-h-[50vh] flex flex-col items-center justify-center text-center text-gray-500 dark:text-gray-400">
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
                        className="transform transition-transform duration-200 hover:scale-105 relative flex h-[197px] flex-col justify-between rounded-[5.86px] border border-[#D1D9E0] dark:border-[#6A6A6A] overflow-hidden cursor-pointer w-full max-w-[487px]"
                        onClick={() => {
                          setEditingChunk(chunk);
                          setEditingTitle(chunk.metadata?.title || '');
                          setEditingText(chunk.text || '');
                        }}
                      >
                        <div className="w-full">
                          <div className="flex w-full items-center justify-between border-b border-[#D1D9E0] bg-[#F6F8FA] dark:bg-[#27282D] dark:border-[#6A6A6A] px-4 py-3">
                            <div className="text-[#59636E] text-sm dark:text-[#E0E0E0]">
                              {chunk.metadata.token_count ? chunk.metadata.token_count.toLocaleString() : '-'} {t('settings.sources.tokensUnit')}
                            </div>
                          </div>
                          <div className="px-4 pt-3 pb-6">
                            <p className="font-['Inter'] text-[13.68px] leading-[19.93px] text-[#18181B] dark:text-[#E0E0E0] line-clamp-6 font-normal">
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
              <div className="relative border border-[#D1D9E0] dark:border-[#6A6A6A] rounded-lg overflow-hidden">
                <LineNumberedTextarea
                  value={editingText}
                  onChange={setEditingText}
                  ariaLabel={t('modals.chunk.promptText')}
                  editable={true}
                />
              </div>
            </div>
          ) : editingChunk && (
            <div className="w-full">
              <div className="relative flex flex-col rounded-[5.86px] border border-[#D1D9E0] dark:border-[#6A6A6A] overflow-hidden w-full">
                <div className="flex w-full items-center justify-between border-b border-[#D1D9E0] bg-[#F6F8FA] dark:bg-[#27282D] dark:border-[#6A6A6A] px-4 py-3">
                  <div className="text-[#59636E] text-sm dark:text-[#E0E0E0]">
                    {editingChunk.metadata.token_count ? editingChunk.metadata.token_count.toLocaleString() : '-'} {t('settings.sources.tokensUnit')}
                  </div>
                </div>
                <div className="p-4 overflow-hidden">
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
          )}

          {!loading && totalChunks > perPage && !editingChunk && !isAddingChunk && (
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
