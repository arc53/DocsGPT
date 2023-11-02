import { useEffect, useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import Edit from '../assets/edit.svg';
import Exit from '../assets/exit.svg';
import Message from '../assets/message.svg';
import CheckMark2 from '../assets/checkMark2.svg';
import Trash from '../assets/trash.svg';

import { selectConversationId } from '../preferences/preferenceSlice';

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

  const [isEdit, setIsEdit] = useState(false);
  const [conversationName, setConversationsName] = useState('');
  // useOutsideAlerter(
  //   tileRef,
  //   () =>
  //     handleSaveConversation({
  //       id: conversationId || conversation.id,
  //       name: conversationName,
  //     }),
  //   [conversationName],
  // );

  useEffect(() => {
    setConversationsName(conversation.name);
  }, [conversation.name]);

  function handleEditConversation() {
    setIsEdit(true);
  }

  function handleSaveConversation(changedConversation: ConversationProps) {
    if (changedConversation.name.trim().length) {
      onSave(changedConversation);
      setIsEdit(false);
    } else {
      onClear();
    }
  }

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
      className={`my-auto mx-4 mt-4 flex h-9 cursor-pointer items-center justify-between gap-4 rounded-3xl hover:bg-gray-100 ${
        conversationId === conversation.id ? 'bg-gray-100' : ''
      }`}
    >
      <div
        className={`flex ${
          conversationId === conversation.id ? 'w-[75%]' : 'w-[95%]'
        } gap-4`}
      >
        <img src={Message} className="ml-4 w-5"></img>
        {isEdit ? (
          <input
            autoFocus
            type="text"
            className="h-6 w-full px-1 text-sm font-normal leading-6 outline-[#0075FF] focus:outline-1"
            value={conversationName}
            onChange={(e) => setConversationsName(e.target.value)}
          />
        ) : (
          <p className="my-auto overflow-hidden overflow-ellipsis whitespace-nowrap text-sm font-normal leading-6 text-eerie-black">
            {conversationName}
          </p>
        )}
      </div>
      {conversationId === conversation.id && (
        <div className="flex">
          <img
            src={isEdit ? CheckMark2 : Edit}
            alt="Edit"
            className="mr-2 h-4 w-4 cursor-pointer hover:opacity-50"
            id={`img-${conversation.id}`}
            onClick={(event) => {
              event.stopPropagation();
              isEdit
                ? handleSaveConversation({
                    id: conversationId,
                    name: conversationName,
                  })
                : handleEditConversation();
            }}
          />
          <img
            src={isEdit ? Exit : Trash}
            alt="Exit"
            className={`mr-4 ${
              isEdit ? 'h-3 w-3' : 'h-4 w-4'
            }mt-px  cursor-pointer hover:opacity-50`}
            id={`img-${conversation.id}`}
            onClick={(event) => {
              event.stopPropagation();
              isEdit ? onClear() : onDeleteConversation(conversation.id);
            }}
          />
        </div>
      )}
    </div>
  );
}
