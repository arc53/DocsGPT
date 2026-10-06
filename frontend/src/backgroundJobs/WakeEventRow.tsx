import { BellRing, ChevronDown } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { cn } from '@/lib/utils';

import {
  humanTitle,
  wakeLabelKey,
  wakeTitle,
  type WakeEvent,
  type WakeInfo,
} from './kinds';

/** Job statuses the card already has words for. */
const STATUSES = new Set([
  'working',
  'completed',
  'failed',
  'cancelled',
  'lost',
]);

const STATUS_BADGE: Record<
  string,
  'success' | 'destructive' | 'neutral' | 'warning'
> = {
  completed: 'success',
  failed: 'destructive',
  cancelled: 'neutral',
  lost: 'warning',
};

/**
 * A continuation turn's prompt is the event that woke the agent, not
 * something the user wrote: a compact system row ("Background job finished ·
 * Run code"). Unfolded, it lists each event as a person reads it (what it
 * was, its status, a short result); the event text written for the model,
 * with its instructions and data fences, is never shown.
 */
export default function WakeEventRow({
  wake,
  prompt,
  className,
}: {
  wake: WakeInfo;
  prompt: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const events: WakeEvent[] = wake.events ?? [];
  const title = events[0]?.label || humanTitle(wakeTitle(prompt));
  const more = wake.count > 1 ? wake.count - 1 : 0;
  const details = events.filter((event) => event.label || event.detail);
  const expandable =
    details.some((event) => event.detail) || details.length > 1;

  const header = (
    <>
      <BellRing aria-hidden className="text-muted-foreground" />
      <span className="text-muted-foreground shrink-0">
        {t(wakeLabelKey(wake.source))}
      </span>
      {title && (
        <span
          className="text-muted-foreground/70 min-w-0 truncate"
          title={title}
        >
          {title}
        </span>
      )}
      {more > 0 && (
        <span className="text-muted-foreground shrink-0 text-xs">
          {t('backgroundJobs.wake.more', { count: more })}
        </span>
      )}
    </>
  );

  return (
    <div
      className={cn('flex w-full min-w-0 flex-col', className)}
      data-testid="wake-event-row"
    >
      {expandable ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="ml-3.5 w-fit max-w-full justify-start"
        >
          {header}
          <ChevronDown
            aria-hidden
            className={cn(
              'text-muted-foreground shrink-0 transition-transform duration-200',
              open ? 'rotate-180' : '',
            )}
          />
        </Button>
      ) : (
        <div className="ml-3.5 flex h-8 w-fit max-w-full items-center gap-1.5 px-2.5 text-sm [&_svg]:size-4 [&_svg]:shrink-0">
          {header}
        </div>
      )}
      {open && expandable && (
        <ul
          className="mt-2 mr-5 ml-6 flex flex-col gap-3"
          data-testid="wake-event-details"
        >
          {details.map((event, index) => (
            <li key={index} className="flex min-w-0 flex-col gap-1 text-sm">
              <div className="flex min-w-0 items-center gap-2">
                {event.label && (
                  <span className="text-foreground min-w-0 truncate font-medium">
                    {event.label}
                  </span>
                )}
                {event.status && STATUSES.has(event.status) && (
                  <Badge variant={STATUS_BADGE[event.status] ?? 'neutral'}>
                    {t(`backgroundJobs.card.status.${event.status}`)}
                  </Badge>
                )}
              </div>
              {event.detail && (
                <p className="text-muted-foreground wrap-break-word whitespace-pre-wrap">
                  {event.detail}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
