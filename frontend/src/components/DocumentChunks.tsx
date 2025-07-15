import React, { useState, useEffect } from 'react';
import { useSelector } from 'react-redux';
import { useTranslation } from 'react-i18next';
import { selectToken } from '../preferences/preferenceSlice';
import { useDarkTheme, useLoaderState } from '../hooks';
import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import NoFilesIcon from '../assets/no-files.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import Spinner from '../components/Spinner';
import Input from '../components/Input';
import ChunkModal from '../modals/ChunkModal';
import { ActiveState } from '../models/misc';
import { ChunkType } from '../settings/types';

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
  }, [page, perPage]);

  return (
    <div className="mt-8 flex flex-col">
      {showHeader && (
        <div className="text-eerie-black dark:text-bright-gray mb-3 flex items-center gap-3 text-sm">
          <button
            className="rounded-full border p-3 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
            onClick={handleGoBack}
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
          </button>
          <p className="mt-px">{t('settings.documents.backToAll')}</p>
        </div>
      )}
      <div className="my-3 flex items-center justify-between gap-1">
        <div className="text-eerie-black dark:text-bright-gray flex w-full items-center gap-2 sm:w-auto">
          <p className="hidden text-2xl font-semibold sm:flex">{`${totalChunks} ${t('settings.documents.chunks')}`}</p>
          <label htmlFor="chunk-search-input" className="sr-only">
            {t('settings.documents.searchPlaceholder')}
          </label>
          <Input
            maxLength={256}
            placeholder={t('settings.documents.searchPlaceholder')}
            name="chunk-search-input"
            type="text"
            id="chunk-search-input"
            value={searchTerm}
            onChange={(e) => {
              setSearchTerm(e.target.value);
            }}
            borderVariant="thin"
          />
        </div>
        <button
          className="bg-purple-30 hover:bg-violets-are-blue flex h-[32px] min-w-[108px] items-center justify-center rounded-full px-4 text-sm whitespace-normal text-white"
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
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {paginatedChunks.filter((chunk) => {
            if (!chunk.metadata?.title) return true;
            return chunk.metadata.title
              .toLowerCase()
              .includes(searchTerm.toLowerCase());
          }).length === 0 ? (
            <div className="col-span-2 mt-24 text-center text-gray-500 lg:col-span-3 dark:text-gray-400">
              <img
                src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                alt={t('settings.documents.noChunksAlt')}
                className="mx-auto mb-2 h-24 w-24"
              />
              {t('settings.documents.noChunks')}
            </div>
          ) : (
            paginatedChunks
              .filter((chunk) => {
                if (!chunk.metadata?.title) return true;
                return chunk.metadata.title
                  .toLowerCase()
                  .includes(searchTerm.toLowerCase());
              })
              .map((chunk, index) => (
                <div
                  key={index}
                  className="border-silver dark:border-silver/40 relative flex h-56 w-full flex-col justify-between rounded-2xl border p-6"
                >
                  <div className="w-full">
                    <div className="flex w-full items-center justify-between">
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
                        <h3 className="text-eerie-black dark:text-bright-gray line-clamp-2 text-base font-semibold">
                          {chunk.metadata?.title ||
                            t('settings.documents.untitled')}
                        </h3>
                      </button>
                    </div>
                    <div className="mt-2 h-[80px] overflow-hidden">
                      <p className="text-eerie-black dark:text-bright-gray line-clamp-4 text-sm">
                        {chunk.text}
                      </p>
                    </div>
                  </div>
                </div>
              ))
          )}
        </div>
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
