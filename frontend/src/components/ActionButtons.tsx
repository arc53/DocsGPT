import { Share } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { ShareConversationModal } from '../modals/ShareConversationModal';
import { useState } from 'react';
import { selectConversationId } from '../preferences/preferenceSlice';
import { IconButton } from './ui/icon-button';
import ProfileButton from './ProfileButton';
import { cn } from '@/lib/utils';

interface ActionButtonsProps {
  className?: string;
  showShare?: boolean;
  isArtifactOpen?: boolean;
}

/**
 * Share and the account menu in the desktop top-right corner. Below `lg`
 * the same actions live in `MobileTopBar`.
 */
export default function ActionButtons({
  className = '',
  showShare = true,
  isArtifactOpen = false,
}: ActionButtonsProps) {
  const { t } = useTranslation();
  const conversationId = useSelector(selectConversationId);
  const [isShareModalOpen, setShareModalState] = useState<boolean>(false);

  return (
    <div
      className={cn(
        'fixed top-0 z-10 hidden h-16 flex-col justify-center transition-[right] duration-300 ease-in-out lg:flex',
        isArtifactOpen ? 'right-[calc(50%+1rem)]' : 'right-4',
      )}
    >
      <div className={cn('flex items-center gap-2 sm:gap-4', className)}>
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
