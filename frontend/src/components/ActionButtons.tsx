import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import newChatIcon from '../assets/openNewChat.svg';
import ShareIcon from '../assets/share.svg';
import { ShareConversationModal } from '../modals/ShareConversationModal';
import { useState } from 'react';
import { selectConversationId } from '../preferences/preferenceSlice';
import { useDispatch } from 'react-redux';
import { AppDispatch } from '../store';
import {
  setConversation,
  updateConversationId,
} from '../conversation/conversationSlice';

interface ActionButtonsProps {
  className?: string;
  showNewChat?: boolean;
  showShare?: boolean;
}

import { useNavigate } from 'react-router-dom';

export default function ActionButtons({
  className = '',
  showNewChat = true,
  showShare = true,
}: ActionButtonsProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const conversationId = useSelector(selectConversationId);
  const [isShareModalOpen, setShareModalState] = useState<boolean>(false);
  const navigate = useNavigate();

  const newChat = () => {
    dispatch(setConversation([]));
    dispatch(
      updateConversationId({
        query: { conversationId: null },
      }),
    );
    navigate('/');
  };
  return (
    <div className="fixed right-4 top-0 z-10 flex h-16 flex-col justify-center">
      <div className={`flex items-center gap-2 sm:gap-4 ${className}`}>
        {showNewChat && (
          <button
            title="Open New Chat"
            onClick={newChat}
            className="flex items-center gap-1 rounded-full p-2 hover:bg-bright-gray dark:hover:bg-[#28292E] lg:hidden"
          >
            <img
              className="filter dark:invert"
              alt="NewChat"
              width={21}
              height={21}
              src={newChatIcon}
            />
          </button>
        )}

        {showShare && conversationId && (
          <>
            <button
              title="Share"
              onClick={() => setShareModalState(true)}
              className="rounded-full p-2 hover:bg-bright-gray dark:hover:bg-[#28292E]"
            >
              <img
                className="filter dark:invert"
                alt="share"
                width={16}
                height={16}
                src={ShareIcon}
              />
            </button>
            {isShareModalOpen && (
              <ShareConversationModal
                close={() => setShareModalState(false)}
                conversationId={conversationId}
              />
            )}
          </>
        )}
        <div>{/* <UserButton  /> */}</div>
      </div>
    </div>
  );
}
