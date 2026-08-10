import { useTranslation } from 'react-i18next';

import { cn } from '../lib/utils';

type StreamingStatusLineProps = {
  hasAnswerText?: boolean;
  className?: string;
};

/**
 * Only renders while no step chip is live above it, since chips announce their
 * own activity. That leaves the two states nothing else covers.
 */
export default function StreamingStatusLine({
  hasAnswerText = false,
  className,
}: StreamingStatusLineProps) {
  const { t } = useTranslation();

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn('flex h-6 min-w-0 items-center gap-2', className)}
    >
      <span className="shimmer-text max-w-[70vw] truncate text-sm lg:max-w-md">
        {hasAnswerText
          ? t('conversation.streamingStatus.generating')
          : t('conversation.streamingStatus.thinking')}
      </span>
    </div>
  );
}
