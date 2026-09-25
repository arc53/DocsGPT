import { Plus, Share } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { ShareConversationModal } from '../modals/ShareConversationModal';
import { useState } from 'react';
import { selectConversationId } from '../preferences/preferenceSlice';
import { useDispatch } from 'react-redux';
import { AppDispatch } from '../store';
import {
  setConversation,
  updateConversationId,
} from '../conversation/conversationSlice';
import { Button } from './ui/button';
import ProfileButton from './ProfileButton';

interface ActionButtonsProps {
  className?: string;
  showNewChat?: boolean;
  showShare?: boolean;
  isArtifactOpen?: boolean;
}

import { useNavigate } from 'react-router-dom';

export default function ActionButtons({
  className = '',
  showNewChat = true,
  showShare = true,
  isArtifactOpen = false,
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
    navigate('/c/new');
  };
  return (
    <div
      className={`fixed top-0 z-10 flex h-16 flex-col justify-center transition-all duration-300 ${
        isArtifactOpen ? 'right-[calc(50%+1rem)]' : 'right-4'
      }`}
    >
      <div className={`flex items-center gap-2 sm:gap-4 ${className}`}>
        {showNewChat && (
          <Button
            type="button"
            variant="ghost-muted"
            size="icon"
            shape="pill"
            title={t('actionButtons.openNewChat')}
            onClick={newChat}
            className="lg:hidden"
          >
            <Plus className="size-5" aria-label="NewChat" />
          </Button>
        )}

        {showShare && conversationId && (
          <>
            <Button
              type="button"
              variant="ghost-muted"
              size="icon"
              shape="pill"
              title={t('actionButtons.share')}
              onClick={() => setShareModalState(true)}
            >
              <Share className="size-5" aria-label="share" />
            </Button>
            {isShareModalOpen && (
              <ShareConversationModal
                close={() => setShareModalState(false)}
                conversationId={conversationId}
              />
            )}
          </>
        )}
        <ProfileButton />
      </div>
    </div>
  );
}
