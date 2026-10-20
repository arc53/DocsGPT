import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

import { selectSignInNeededCount } from '../connectors/connectorsSlice';
import { formatCount } from '../utils/dateTimeUtils';
import { selectActivityNow, selectLiveConversations } from './activitySlice';

export type ActivitySummary = {
  running: number;
  needsYou: number;
  /** Something in "Needs you" failed (a schedule paused after failures). */
  failed: boolean;
};

/**
 * The Activity counts, one definition for the sidebar and Now: running is
 * the rows Now lists (an API row is one; it says how many requests) plus
 * chats that started since the snapshot; needs-you is its items plus each
 * connection to sign in to again.
 */
export function useActivitySummary(): ActivitySummary {
  const now = useSelector(selectActivityNow);
  const live = useSelector(selectLiveConversations);
  const reconnects = useSelector(selectSignInNeededCount);
  const runningChats = new Set(
    (now?.running ?? [])
      .filter((item) => item.kind === 'chat' && item.conversation_id)
      .map((item) => item.conversation_id as string),
  );
  // Chats that started since the snapshot (`message.started`) count at once.
  const started = Object.keys(live).filter(
    (id) => !runningChats.has(id),
  ).length;
  const needs = now?.needs_you ?? [];
  return {
    running: (now?.running.length ?? 0) + started,
    needsYou: needs.length + reconnects,
    failed: needs.some((item) => item.kind === 'schedule_paused'),
  };
}

/**
 * The id of the rail's counts. The rail's icon button is named by its
 * `aria-label`, which hides any text inside it, so it points
 * `aria-describedby` here.
 */
export const RAIL_STATUS_ID = 'activity-rail-status';

/**
 * The trailing marks of the sidebar's Activity row: a red or amber dot while
 * something needs the user (red when it failed), and how many things run.
 * `rail` draws only the dot, on the collapsed sidebar's icon.
 */
export default function ActivityNavBadge({
  variant = 'row',
}: {
  variant?: 'row' | 'rail';
}) {
  const { t } = useTranslation();
  const { running, needsYou, failed } = useActivitySummary();
  const label = [
    running > 0
      ? t('activity.nav.running', {
          count: running,
          formatted: formatCount(running),
        })
      : null,
    needsYou > 0
      ? t('activity.nav.needsYou', {
          count: needsYou,
          formatted: formatCount(needsYou),
        })
      : null,
  ]
    .filter(Boolean)
    .join(' · ');
  if (!label) return null;
  const dot = needsYou > 0 && (
    <span
      aria-hidden
      className={cn(
        'size-2 shrink-0 rounded-full',
        failed ? 'bg-destructive' : 'bg-warning',
        variant === 'rail' && 'absolute top-1.5 right-1.5',
      )}
    />
  );
  if (variant === 'rail') {
    return (
      <>
        {dot}
        <span id={RAIL_STATUS_ID} className="sr-only">
          {label}
        </span>
      </>
    );
  }
  // The dot and the bare number say what they count in a tooltip; a screen
  // reader reads the same words from the hidden label, part of the row's name.
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="ms-auto flex shrink-0 items-center gap-2 pe-3">
          {dot}
          {running > 0 && (
            <span className="text-muted-foreground text-xs tabular-nums">
              {formatCount(running)}
            </span>
          )}
          <span className="sr-only">{label}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}
