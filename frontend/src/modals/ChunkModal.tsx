import React from 'react';

import Exit from '../assets/exit.svg';
import Input from '../components/Input';
import { ActiveState } from '../models/misc';
import ConfirmationModal from './ConfirmationModal';

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
  const [title, setTitle] = React.useState('');
  const [chunkText, setChunkText] = React.useState('');
  const [deleteModal, setDeleteModal] = React.useState<ActiveState>('INACTIVE');

  React.useEffect(() => {
    setTitle(originalTitle || '');
    setChunkText(originalText || '');
  }, [originalTitle, originalText]);
  if (type === 'ADD') {
    return (
      <div
        className={`${
          modalState === 'ACTIVE' ? 'visible' : 'hidden'
        } fixed left-0 top-0 z-30 flex h-screen w-screen items-center justify-center bg-gray-alpha`}
      >
        <article className="flex w-11/12 flex-col gap-4 rounded-2xl bg-white shadow-lg dark:bg-[#26272E] sm:w-[620px]">
          <div className="relative">
            <button
              className="absolute right-4 top-3 m-2 w-3"
              onClick={() => {
                setModalState('INACTIVE');
              }}
            >
              <img className="filter dark:invert" src={Exit} />
            </button>
            <div className="p-6">
              <h2 className="px-3 text-xl font-semibold text-jet dark:text-bright-gray">
                Add Chunk
              </h2>
              <div className="relative mt-6 px-3">
                <span className="absolute -top-2 left-5 z-10 bg-white px-2 text-xs text-gray-4000 dark:bg-[#26272E] dark:text-silver">
                  Title
                </span>
                <Input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  borderVariant="thin"
                  placeholder={'Enter title'}
                  labelBgClassName="bg-white dark:bg-charleston-green-2"
                ></Input>
              </div>
              <div className="relative mt-6 px-3">
                <div className="rounded-lg border border-silver pb-1 pt-3 dark:border-silver/40">
                  <span className="absolute -top-2 left-5 rounded-lg bg-white px-2 text-xs text-gray-4000 dark:bg-[#26272E] dark:text-silver">
                    Body text
                  </span>
                  <textarea
                    id="chunk-body-text"
                    className="h-60 w-full px-3 outline-none dark:bg-transparent dark:text-white"
                    value={chunkText}
                    onChange={(e) => setChunkText(e.target.value)}
                    aria-label="Prompt Text"
                  ></textarea>
                </div>
              </div>
              <div className="mt-8 flex flex-row-reverse gap-1 px-3">
                <button
                  onClick={() => {
                    handleSubmit(title, chunkText);
                    setModalState('INACTIVE');
                  }}
                  className="rounded-3xl bg-purple-30 px-5 py-2 text-sm text-white transition-all hover:bg-violets-are-blue"
                >
                  Add
                </button>
                <button
                  onClick={() => {
                    setModalState('INACTIVE');
                  }}
                  className="cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:text-light-gray dark:hover:bg-[#767183]/50"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </article>
      </div>
    );
  } else {
    return (
      <div
        className={`${
          modalState === 'ACTIVE' ? 'visible' : 'hidden'
        } fixed left-0 top-0 z-30 flex h-screen w-screen items-center justify-center bg-gray-alpha`}
      >
        <article className="flex w-11/12 flex-col gap-4 rounded-2xl bg-white shadow-lg dark:bg-[#26272E] sm:w-[620px]">
          <div className="relative">
            <button
              className="absolute right-4 top-3 m-2 w-3"
              onClick={() => {
                setModalState('INACTIVE');
              }}
            >
              <img className="filter dark:invert" src={Exit} />
            </button>
            <div className="p-6">
              <h2 className="px-3 text-xl font-semibold text-jet dark:text-bright-gray">
                Edit Chunk
              </h2>
              <div className="relative mt-6 px-3">
                <Input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  borderVariant="thin"
                  placeholder={'Enter title'}
                  labelBgClassName="bg-white dark:bg-charleston-green-2"
                ></Input>
              </div>
              <div className="relative mt-6 px-3">
                <div className="rounded-lg border border-silver pb-1 pt-3 dark:border-silver/40">
                  <span className="absolute -top-2 left-5 rounded-lg bg-white px-2 text-xs text-gray-4000 dark:bg-[#26272E] dark:text-silver">
                    Body text
                  </span>
                  <textarea
                    id="chunk-body-text"
                    className="h-60 w-full px-3 outline-none dark:bg-transparent dark:text-white"
                    value={chunkText}
                    onChange={(e) => setChunkText(e.target.value)}
                    aria-label="Prompt Text"
                  ></textarea>
                </div>
              </div>
              <div className="mt-8 flex w-full items-center justify-between px-3">
                <button
                  className="text-nowrap rounded-full border border-solid border-red-500 px-5 py-2 text-sm text-red-500 hover:bg-red-500 hover:text-white"
                  onClick={() => {
                    setDeleteModal('ACTIVE');
                  }}
                >
                  Delete
                </button>
                <div className="flex flex-row-reverse gap-1">
                  <button
                    onClick={() => {
                      handleSubmit(title, chunkText);
                      setModalState('INACTIVE');
                    }}
                    className="rounded-3xl bg-purple-30 px-5 py-2 text-sm text-white transition-all hover:bg-violets-are-blue"
                  >
                    Update
                  </button>
                  <button
                    onClick={() => {
                      setModalState('INACTIVE');
                    }}
                    className="cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:text-light-gray dark:hover:bg-[#767183]/50"
                  >
                    Close
                  </button>
                </div>
              </div>
            </div>
          </div>
        </article>
        <ConfirmationModal
          message="Are you sure you want to delete this chunk?"
          modalState={deleteModal}
          setModalState={setDeleteModal}
          handleSubmit={
            handleDelete
              ? handleDelete
              : () => {
                  /* no-op */
                }
          }
          submitLabel="Delete"
        />
      </div>
    );
  }
}
