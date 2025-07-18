import React, { useState, useEffect } from 'react';
import { useSelector } from 'react-redux';
import { useTranslation } from 'react-i18next';
import { selectToken } from '../preferences/preferenceSlice';
import { useDarkTheme, useLoaderState } from '../hooks';
import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import NoFilesIcon from '../assets/no-files.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import OutlineSource from '../assets/outline-source.svg';
import Spinner from '../components/Spinner';
import ChunkModal from '../modals/ChunkModal';
import { ActiveState } from '../models/misc';
import { ChunkType } from '../settings/types';
import EditIcon from '../assets/edit.svg';
import Pagination from './DocumentPagination';

interface DocumentChunksProps {
  documentId: string;
  documentName?: string;
  handleGoBack: () => void;
  showHeader?: boolean;
  path?: string;
}

const DocumentChunks: React.FC<DocumentChunksProps> = ({
  documentId,
  documentName,
  handleGoBack,
  showHeader = true,
  path,
}) => {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [isDarkTheme] = useDarkTheme();
  const [paginatedChunks, setPaginatedChunks] = useState<ChunkType[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(5);
  const [totalChunks, setTotalChunks] = useState(0);
  const [loading, setLoading] = useLoaderState(true);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [addModal, setAddModal] = useState<ActiveState>('INACTIVE');
  const [editModal, setEditModal] = useState<{
    state: ActiveState;
    chunk: ChunkType | null;
  }>({ state: 'INACTIVE', chunk: null });

  const pathParts = path ? path.split('/') : [];

  const fetchChunks = () => {
    setLoading(true);
    try {
      userService
        .getDocumentChunks(documentId, page, perPage, token, path)
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
        });
    } catch (e) {
      console.log(e);
      setLoading(false);
    }
  };

  const handleAddChunk = (title: string, text: string) => {
    try {
      userService
        .addChunk(
          {
            id: documentId,
            text: text,
            metadata: {
              title: title,
            },
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
          setEditModal({ state: 'INACTIVE', chunk: null });
          fetchChunks();
        });
    } catch (e) {
      console.log(e);
    }
  };

  useEffect(() => {
    fetchChunks();
  }, [page, perPage, path]);

  const filteredChunks = paginatedChunks.filter((chunk) => {
    if (!chunk.metadata?.title) return true;
    return chunk.metadata.title
      .toLowerCase()
      .includes(searchTerm.toLowerCase());
  });

  return (
    <div className={`${showHeader ? 'mt-8' : 'mt-0'} flex flex-col`}>
      {showHeader && (
        <div className="mb-4 flex items-center">
          <button
            className="mr-3 flex h-[29px] w-[29px] items-center justify-center rounded-full border p-2 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
            onClick={handleGoBack}
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
          </button>

          <div className="flex items-center">
            <img src={OutlineSource} alt="source" className="mr-2 h-5 w-5" />
            <span className="text-[#7D54D1] font-semibold text-base leading-6">
              {documentName}
            </span>

            {pathParts.length > 0 && (
              <>
                <span className="mx-1 text-gray-500">/</span>
                {pathParts.map((part, index) => (
                  <React.Fragment key={index}>
                    <span className="font-normal text-base leading-6 text-gray-700 dark:text-gray-300">
                      {part}
                    </span>
                    {index < pathParts.length - 1 && (
                      <span className="mx-1 text-gray-500">/</span>
                    )}
                  </React.Fragment>
                ))}
              </>
            )}
          </div>
        </div>
      )}

      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex-1 flex items-center border border-[#D1D9E0] dark:border-[#6A6A6A] rounded-md overflow-hidden h-[38px]">
          <div className="px-4 flex items-center text-gray-700 dark:text-[#E0E0E0] font-medium whitespace-nowrap h-full">
            {totalChunks > 999999
              ? `${(totalChunks / 1000000).toFixed(2)}M`
              : totalChunks > 999
                ? `${(totalChunks / 1000).toFixed(2)}K`
                : totalChunks} {t('settings.documents.chunks')}
          </div>
          <div className="h-full w-[1px] bg-[#D1D9E0] dark:bg-[#6A6A6A]"></div>
          <div className="flex-1 h-full">
            <input
              type="text"
              placeholder={t('settings.documents.searchPlaceholder')}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full h-full px-3 py-2 bg-transparent border-none outline-none font-normal text-[13.56px] leading-[100%] dark:text-[#E0E0E0]"
            />
          </div>
        </div>
        <button
          className="bg-purple-30 hover:bg-violets-are-blue flex h-[38px] min-w-[108px] items-center justify-center rounded-full px-4 text-sm whitespace-normal text-white shrink-0"
          title={t('settings.documents.addNew')}
          onClick={() => setAddModal('ACTIVE')}
        >
          {t('settings.documents.addNew')}
        </button>
      </div>
      {loading ? (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          <div className="col-span-2 mt-24 flex h-32 items-center justify-center lg:col-span-3">
            <Spinner />
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-4">
          {filteredChunks.length === 0 ? (
            <div className="w-full flex flex-col items-center justify-center mt-24 text-center text-gray-500 dark:text-gray-400">
              <img
                src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                alt={t('settings.documents.noChunksAlt')}
                className="mx-auto mb-2 h-24 w-24"
              />
              {t('settings.documents.noChunks')}
            </div>
          ) : (
            filteredChunks.map((chunk, index) => (
              <div
                key={index}
                className="relative flex h-[208px] w-[400px] flex-col justify-between rounded-[5.86px] border border-[#D1D9E0] dark:border-[#6A6A6A] overflow-hidden"
              >
                <div className="w-full">
                  <div className="flex w-full items-center justify-between border-b border-[#D1D9E0] bg-[#F6F8FA] dark:bg-[#27282D] dark:border-[#6A6A6A] px-4 py-3">
                    <div className="text-[#59636E] text-sm dark:text-[#E0E0E0]">
                      {chunk.metadata.token_count ? chunk.metadata.token_count.toLocaleString() : '-'} tokens
                    </div>
                    <button
                      aria-label={'edit'}
                      onClick={() => {
                        setEditModal({
                          state: 'ACTIVE',
                          chunk: chunk,
                        });
                      }}
                      className="text-left"
                    >
                      <img src={EditIcon} alt="edit" className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="p-4">
                    <p className="font-['Inter'] text-[13.68px] leading-[19.93px] text-[#18181B] dark:text-[#E0E0E0] line-clamp-7 font-normal">
                      {chunk.text}
                    </p>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {!loading && filteredChunks.length > 0 && (
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

      <ChunkModal
        type="ADD"
        modalState={addModal}
        setModalState={setAddModal}
        handleSubmit={handleAddChunk}
      />
      {editModal.chunk && (
        <ChunkModal
          type="EDIT"
          modalState={editModal.state}
          setModalState={(state) =>
            setEditModal((prev) => ({ ...prev, state }))
          }
          handleSubmit={(title, text) => {
            handleUpdateChunk(title, text, editModal.chunk as ChunkType);
          }}
          originalText={editModal.chunk?.text ?? ''}
          originalTitle={editModal.chunk?.metadata?.title ?? ''}
          handleDelete={() => {
            handleDeleteChunk(editModal.chunk as ChunkType);
          }}
        />
      )}
    </div>
  );
};

export default DocumentChunks;
