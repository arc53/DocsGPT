import { useTranslation } from 'react-i18next';

import { Card } from '../components/ui/card';
import { Skeleton } from '../components/ui/skeleton';

/**
 * A chat that is still loading: question and answer rows as bars, on the
 * message column's margins. Shown instead of the empty chat's hero, which
 * read as a new chat and offered suggestions that would start one.
 */
export default function ChatLoadingSkeleton() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col">
      {/* The bars are aria-hidden; this tells a screen reader why. */}
      <span className="sr-only" role="status">
        {t('loading')}
      </span>
      {/* Two turns: a question bubble's place, right-aligned and one line
          tall, over its answer's lines. */}
      <div className="mt-5 mr-2 mb-3 flex justify-end">
        <Skeleton className="h-14 w-2/5 max-w-80" />
      </div>
      <div className="mr-5 mb-7 ml-6 flex flex-col gap-3 py-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-11/12" />
        <Skeleton className="h-4 w-4/5" />
        <Skeleton className="h-4 w-3/5" />
      </div>
      <div className="mr-2 mb-3 flex justify-end">
        <Skeleton className="h-14 w-1/3 max-w-72" />
      </div>
      <div className="mr-5 mb-7 ml-6 flex flex-col gap-3 py-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    </div>
  );
}

/** The agent card's place while the agent of a loading chat is read. */
export function AgentCardSkeleton() {
  return (
    <Card
      variant="filled"
      padding="lg"
      aria-hidden="true"
      className="w-full max-w-[720px] sm:w-fit sm:min-w-[480px]"
    >
      <div className="flex items-start gap-3">
        <Skeleton surface="muted" className="size-12 rounded-full" />
        <div className="flex min-w-0 flex-1 flex-col gap-2 pt-1">
          <Skeleton surface="muted" className="h-5 w-1/2" />
          <Skeleton surface="muted" className="h-3 w-full" />
          <Skeleton surface="muted" className="h-3 w-4/5" />
        </div>
      </div>
    </Card>
  );
}
