import React, { useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import Edit from '../assets/edit.svg';
import Exit from '../assets/exit.svg';
import Message from '../assets/message.svg';
import CheckMark from '../assets/checkMark.svg';

import { selectConversationId } from '../preferences/preferenceSlice';

interface ConversationTileProps {
  conversation: { name: string; id: string };
  selectConversation: (arg1: string) => void;
  onDeleteConversation: (arg1: string) => void;
  onSave: ({ name, id }: { name: string; id: string }) => void;
}

export default function ConversationTile({
  conversation,
  selectConversation,
  onDeleteConversation,
  onSave,
}: ConversationTileProps) {
  const conversationId = useSelector(selectConversationId);
  const inputRef = useRef<HTMLInputElement>(null);

  const [isEdit, setIsEdit] = useState(false);
  const [conversationName, setConversationsName] = useState(conversation.name);

  function handleEditConversation() {
    setIsEdit(true);
    // inputRef?.current?.focus();
  }
  function handleSaveConversation(changedConversation: any) {
    onSave(changedConversation);
    setIsEdit(false);
  }
  function handleBlur() {
    if (conversation.name !== conversationName) {
      handleSaveConversation({
        id: conversationId,
        name: conversationName,
      });
    }
  }
  return (
    <div
      onClick={() => {
        selectConversation(conversation.id);
      }}
      className={`my-auto mx-4 mt-4 flex h-12 cursor-pointer items-center justify-between gap-4 rounded-3xl hover:bg-gray-100 ${
        conversationId === conversation.id ? 'bg-gray-100' : ''
      }`}
    >
      <div className="flex gap-4">
        <img src={Message} className="ml-2 w-5"></img>
        {isEdit ? (
          <input
            ref={inputRef}
            autoFocus
            type="text"
            className="h-6 w-full px-1 outline-blue-400 focus:outline-1"
            value={conversationName}
            onBlur={handleBlur}
            onChange={(e) => setConversationsName(e.target.value)}
          />
        ) : (
          <p className="my-auto text-eerie-black">
            {conversationName.length > 45
              ? conversationName.substring(0, 45) + '...'
              : conversationName}
          </p>
        )}
      </div>
      {conversationId === conversation.id ? (
        <>
          <img
            src={isEdit ? CheckMark : Edit}
            alt="Edit"
            className="mr-px h-4 w-4 cursor-pointer hover:opacity-50"
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
            src={Exit}
            alt="Exit"
            className="mr-4 h-3 w-3 cursor-pointer hover:opacity-50"
            id={`img-${conversation.id}`}
            onClick={(event) => {
              event.stopPropagation();
              onDeleteConversation(conversation.id);
            }}
          />
        </>
      ) : null}
    </div>
  );
}
