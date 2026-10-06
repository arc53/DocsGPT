import { Radar } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import type { RootState } from '@/store';

import { selectIsWatching } from './monitorsSlice';

/** The small mark on a conversation that has an active monitor. */
export default function WatchingMark({
  conversationId,
}: {
  conversationId: string;
}) {
  const { t } = useTranslation();
  const watching = useSelector((state: RootState) =>
    selectIsWatching(state, conversationId),
  );
  if (!watching) return null;
  return (
    <Radar
      role="img"
      aria-label={t('monitors.watching')}
      data-testid="watching-mark"
      className="text-muted-foreground size-3.5 shrink-0"
    />
  );
}
