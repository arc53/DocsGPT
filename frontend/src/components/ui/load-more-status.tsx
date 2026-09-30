import { useTranslation } from 'react-i18next';

import { cn } from '@/lib/utils';

import { Button } from './button';
import { Spinner } from './spinner';

type LoadMoreStatusProps = {
  loading: boolean;
  error: boolean;
  /** The oldest item is loaded. */
  done: boolean;
  onRetry: () => void;
  /** A rule above: under a flush table that runs to the card's edges. */
  divider?: boolean;
  /** Wording for a list that isn't a newest-first feed ("Loading more…"). */
  loadingLabel?: string;
  doneLabel?: string;
  className?: string;
};

/**
 * The strip under a newest-first feed: "Loading older…", "Nothing older",
 * or a failed page with Retry. It keeps one row's height while idle, so the
 * list doesn't jump, and sits outside the feed's scroller, which keeps a
 * capped box's scrollbar clear of the card's rounded corner.
 */
function LoadMoreStatus({
  loading,
  error,
  done,
  onRetry,
  divider = false,
  loadingLabel,
  doneLabel,
  className,
}: LoadMoreStatusProps) {
  const { t } = useTranslation();
  return (
    <div
      data-slot="load-more-status"
      aria-live="polite"
      className={cn(
        'text-muted-foreground flex h-9 items-center justify-center gap-2 text-xs',
        divider && 'border-border border-t',
        className,
      )}
    >
      {loading ? (
        <>
          <Spinner size="xs" />
          {loadingLabel ?? t('pagination.loadingOlder')}
        </>
      ) : error ? (
        <>
          {t('pagination.olderFailed')}
          <Button variant="outline" size="xs" onClick={onRetry}>
            {t('retry')}
          </Button>
        </>
      ) : done ? (
        (doneLabel ?? t('pagination.noOlder'))
      ) : null}
    </div>
  );
}

export { LoadMoreStatus };
export type { LoadMoreStatusProps };
