import React from 'react';
import { useTranslation } from 'react-i18next';

import Input from '../components/Input';
import { ActiveState } from '../models/misc';
import ConfirmationModal from './ConfirmationModal';
import WrapperModal from './WrapperModal';

export default function ChunkModal({
  type,
  modalState,
  setModalState,
  handleSubmit,
  originalTitle,
  originalText,
  handleDelete,
}: {
  type: 'ADD' | 'EDIT';
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  handleSubmit: (title: string, text: string) => void;
  originalTitle?: string;
  originalText?: string;
  handleDelete?: () => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = React.useState('');
  const [chunkText, setChunkText] = React.useState('');
  const [deleteModal, setDeleteModal] = React.useState<ActiveState>('INACTIVE');

  React.useEffect(() => {
    setTitle(originalTitle || '');
    setChunkText(originalText || '');
  }, [originalTitle, originalText]);

  const resetForm = () => {
    setTitle('');
    setChunkText('');
  };

  const handleDeleteConfirmed = () => {
    if (handleDelete) {
      handleDelete();
    }
    setDeleteModal('INACTIVE');
    setModalState('INACTIVE');
  };

  if (modalState !== 'ACTIVE') return null;

  const content = (
    <div>
      <h2 className="px-3 text-xl font-semibold text-jet dark:text-bright-gray">
        {t(`modals.chunk.${type === 'ADD' ? 'add' : 'edit'}`)}
      </h2>
      <div className="relative mt-6 px-3">
        <Input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          borderVariant="thin"
          placeholder={t('modals.chunk.title')}
          labelBgClassName="bg-white dark:bg-charleston-green-2"
        />
      </div>
      <div className="relative mt-6 px-3">
        <div className="rounded-lg border border-silver pb-1 pt-3 dark:border-silver/40">
          <span className="absolute -top-2 left-5 rounded-lg bg-white px-2 text-xs text-gray-4000 dark:bg-[#26272E] dark:text-silver">
            {t('modals.chunk.bodyText')}
          </span>
          <textarea
            id="chunk-body-text"
            className="h-60 max-h-60 w-full resize-none px-3 outline-none dark:bg-transparent dark:text-white"
            value={chunkText}
            onChange={(e) => setChunkText(e.target.value)}
            aria-label={t('modals.chunk.promptText')}
          ></textarea>
        </div>
      </div>

      {type === 'ADD' ? (
        <div className="mt-8 flex flex-row-reverse gap-1 px-3">
          <button
            onClick={() => {
              handleSubmit(title, chunkText);
              setModalState('INACTIVE');
              resetForm();
            }}
            className="rounded-3xl bg-purple-30 px-5 py-2 text-sm text-white transition-all hover:bg-violets-are-blue"
          >
            {t('modals.chunk.add')}
          </button>
          <button
            onClick={() => {
              setModalState('INACTIVE');
              resetForm();
            }}
            className="cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:text-light-gray dark:hover:bg-[#767183]/50"
          >
            {t('modals.chunk.close')}
          </button>
        </div>
      ) : (
        <div className="mt-8 flex w-full items-center justify-between px-3">
          <button
            className="text-nowrap rounded-full border border-solid border-red-500 px-5 py-2 text-sm text-red-500 hover:bg-red-500 hover:text-white"
            onClick={() => {
              setDeleteModal('ACTIVE');
            }}
          >
            {t('modals.chunk.delete')}
          </button>
          <div className="flex flex-row-reverse gap-1">
            <button
              onClick={() => {
                handleSubmit(title, chunkText);
                setModalState('INACTIVE');
              }}
              className="rounded-3xl bg-purple-30 px-5 py-2 text-sm text-white transition-all hover:bg-violets-are-blue"
            >
              {t('modals.chunk.update')}
            </button>
            <button
              onClick={() => {
                setModalState('INACTIVE');
              }}
              className="cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:text-light-gray dark:hover:bg-[#767183]/50"
            >
              {t('modals.chunk.close')}
            </button>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <>
      <WrapperModal
        close={() => setModalState('INACTIVE')}
        className="sm:w-[620px]"
        isPerformingTask={true}
      >
        {content}
      </WrapperModal>

      {type === 'EDIT' && (
        <ConfirmationModal
          message={t('modals.chunk.deleteConfirmation')}
          modalState={deleteModal}
          setModalState={setDeleteModal}
          handleSubmit={handleDeleteConfirmed}
          submitLabel={t('modals.chunk.delete')}
        />
      )}
    </>
  );
}
