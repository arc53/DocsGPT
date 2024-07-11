import { useEffect, useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import Edit from '../assets/edit.svg';
import Exit from '../assets/exit.svg';
import Message from '../assets/message.svg';
import MessageDark from '../assets/message-dark.svg';
import { useDarkTheme } from '../hooks';
import ConfirmationModal from '../modals/ConfirmationModal';
import CheckMark2 from '../assets/checkMark2.svg';
import Trash from '../assets/red-trash.svg';
import Share from '../assets/share.svg';
import threeDots from '../assets/three-dots.svg';
import { selectConversationId } from '../preferences/preferenceSlice';
import { ActiveState } from '../models/misc';
import { ShareConversationModal } from '../modals/ShareConversationModal';
interface ConversationProps {
  name: string;
  id: string;
}
interface ConversationTileProps {
  conversation: ConversationProps;
  selectConversation: (arg1: string) => void;
  onDeleteConversation: (arg1: string) => void;
  onSave: ({ name, id }: ConversationProps) => void;
}

export default function ConversationTile({
  conversation,
  selectConversation,
  onDeleteConversation,
  onSave,
}: ConversationTileProps) {
  const conversationId = useSelector(selectConversationId);
  const tileRef = useRef<HTMLInputElement>(null);
  const [isDarkTheme] = useDarkTheme();
  const [isEdit, setIsEdit] = useState(false);
  const [conversationName, setConversationsName] = useState('');
  const [isOpen, setOpen] = useState<boolean>(false);
  const [isShareModalOpen, setShareModalState] = useState<boolean>(false);
  const [deleteModalState, setDeleteModalState] =
    useState<ActiveState>('INACTIVE');
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setConversationsName(conversation.name);
  }, [conversation.name]);

  function handleEditConversation() {
    setIsEdit(true);
    setOpen(false);
  }

  function handleSaveConversation(changedConversation: ConversationProps) {
    if (changedConversation.name.trim().length) {
      onSave(changedConversation);
      setIsEdit(false);
    } else {
      onClear();
    }
  }

  const handleClickOutside = (event: MouseEvent) => {
    if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
      setOpen(false);
    }
  };

  useEffect(() => {
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);
  function onClear() {
    setConversationsName(conversation.name);
    setIsEdit(false);
  }
  return (
    <div
      ref={tileRef}
      onClick={() => {
        selectConversation(conversation.id);
      }}
      className={`my-auto mx-4 mt-4 flex h-9 cursor-pointer items-center justify-between gap-4 rounded-3xl hover:bg-gray-100 dark:hover:bg-[#28292E] ${
        conversationId === conversation.id
          ? 'bg-gray-100 dark:bg-[#28292E]'
          : ''
      }`}
    >
      <div
        className={`flex ${
          conversationId === conversation.id ? 'w-[75%]' : 'w-[95%]'
        } gap-4`}
      >
        <img
          src={isDarkTheme ? MessageDark : Message}
          className="ml-4 w-5 dark:text-white"
        />
        {isEdit ? (
          <input
            autoFocus
            type="text"
            className="h-6 w-full bg-transparent px-1 text-sm font-normal leading-6 focus:outline-[#0075FF]"
            value={conversationName}
            onChange={(e) => setConversationsName(e.target.value)}
          />
        ) : (
          <p className="my-auto overflow-hidden overflow-ellipsis whitespace-nowrap text-sm font-normal leading-6 text-eerie-black dark:text-white">
            {conversationName}
          </p>
        )}
      </div>
      {conversationId === conversation.id && (
        <div className="flex text-white dark:text-[#949494]" ref={menuRef}>
          {isEdit ? (
            <div className="flex gap-1">
              <img
                src={CheckMark2}
                alt="Edit"
                className="mr-2 h-4 w-4 cursor-pointer text-white hover:opacity-50"
                id={`img-${conversation.id}`}
                onClick={(event) => {
                  event.stopPropagation();
                  handleSaveConversation({
                    id: conversationId,
                    name: conversationName,
                  });
                }}
              />
              <img
                src={isEdit ? Exit : Trash}
                alt="Exit"
                className={`mr-4 mt-px h-3 w-3 cursor-pointer hover:opacity-50`}
                id={`img-${conversation.id}`}
                onClick={(event) => {
                  event.stopPropagation();
                  onClear();
                }}
              />
            </div>
          ) : (
            <button onClick={() => setOpen(!isOpen)}>
              <img src={threeDots} className="mr-4 w-2" />
            </button>
          )}
          {isOpen && (
            <div className="flex-start absolute flex w-32 translate-x-1 translate-y-5 flex-col rounded-xl bg-stone-100 text-sm text-black shadow-xl dark:bg-chinese-black dark:text-chinese-silver md:w-36">
              <button
                onClick={() => {
                  setShareModalState(true);
                  setOpen(false);
                }}
                className="flex-start flex items-center gap-4 rounded-t-xl p-3 hover:bg-bright-gray dark:hover:bg-dark-charcoal"
              >
                <img
                  src={Share}
                  alt="Share"
                  width={14}
                  height={14}
                  className="cursor-pointer hover:opacity-50"
                  id={`img-${conversation.id}`}
                />
                <span>Share</span>
              </button>
              <button
                onClick={(event) => {
                  handleEditConversation();
                }}
                className="flex-start flex items-center gap-4 p-3 hover:bg-bright-gray dark:hover:bg-dark-charcoal"
              >
                <img
                  src={Edit}
                  alt="Edit"
                  width={16}
                  height={16}
                  className="cursor-pointer hover:opacity-50"
                  id={`img-${conversation.id}`}
                />
                <span>Rename</span>
              </button>
              <button
                onClick={(event) => {
                  setDeleteModalState('ACTIVE');
                  setOpen(false);
                }}
                className="flex-start flex items-center gap-3 rounded-b-xl p-2 text-red-700 hover:bg-bright-gray dark:hover:bg-dark-charcoal"
              >
                <img
                  src={Trash}
                  alt="Edit"
                  width={24}
                  height={24}
                  className="cursor-pointer hover:opacity-50"
                />
                <span>Delete</span>
              </button>
            </div>
          )}
        </div>
      )}
      <ConfirmationModal
        message={`Are you sure you want to delete this conversation?`}
        modalState={deleteModalState}
        setModalState={setDeleteModalState}
        handleSubmit={() => onDeleteConversation(conversation.id)}
        submitLabel="Delete"
      />
      {isShareModalOpen && conversationId && (
        <ShareConversationModal
          close={() => {
            setShareModalState(false);
          }}
          conversationId={conversationId}
        />
      )}
    </div>
  );
}
