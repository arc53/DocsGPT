import { useState } from 'react';
import ShareIcon from '../assets/share.svg';
import { ShareConversationModal } from '../modals/ShareConversationModal';

type ShareButtonProps = {
  conversationId: string;
};

export default function ShareButton({ conversationId }: ShareButtonProps) {
  const [isShareModalOpen, setShareModalState] = useState<boolean>(false);
  return (
    <>
      <button
        title="Share"
        onClick={() => {
          setShareModalState(true);
        }}
        className="absolute right-20 top-4 z-20 rounded-full hover:bg-bright-gray dark:hover:bg-[#28292E]"
      >
        <img
          className="m-2 h-5 w-5 filter dark:invert"
          alt="share"
          src={ShareIcon}
        />
      </button>
      {isShareModalOpen && (
        <ShareConversationModal
          close={() => {
            setShareModalState(false);
          }}
          conversationId={conversationId}
        />
      )}
    </>
  );
}
