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
import { IconButton } from './ui/icon-button';
import ProfileButton from './ProfileButton';
import { cn } from '@/lib/utils';

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
      className={cn(
        'fixed top-0 z-10 flex h-16 flex-col justify-center transition-[right] duration-300 ease-in-out',
        isArtifactOpen ? 'right-[calc(50%+1rem)]' : 'right-4',
      )}
    >
      <div className={cn('flex items-center gap-2 sm:gap-4', className)}>
        {showNewChat && (
          <IconButton
            label={t('newChat')}
            side="bottom"
            variant="ghost-muted"
            size="icon"
            shape="pill"
            onClick={newChat}
            className="lg:hidden"
          >
            <Plus aria-hidden />
          </IconButton>
        )}

        {showShare && conversationId && (
          <>
            <IconButton
              label={t('actionButtons.share')}
              side="bottom"
              variant="ghost-muted"
              size="icon"
              shape="pill"
              onClick={() => setShareModalState(true)}
            >
              <Share aria-hidden />
            </IconButton>
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
