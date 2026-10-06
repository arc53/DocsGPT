import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { selectIsUnread } from './backgroundSlice';

/** A small brand dot on a sidebar chat that got a message the user has not seen. */
export default function UnreadDot({
  conversationId,
}: {
  conversationId: string;
}) {
  const { t } = useTranslation();
  const unread = useSelector(selectIsUnread(conversationId));
  if (!unread) return null;
  return (
    <span
      role="img"
      aria-label={t('backgroundJobs.unread')}
      data-testid="unread-dot"
      className="bg-primary size-2 shrink-0 rounded-full"
    />
  );
}
