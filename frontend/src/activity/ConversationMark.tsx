import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { Spinner } from '@/components/ui/spinner';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

import { selectIsUnread } from '../backgroundJobs/backgroundSlice';
import { selectIsWatching } from '../monitors/monitorsSlice';
import type { RootState } from '../store';
import {
  selectApprovalConversations,
  selectFailedConversations,
  selectWorkingConversations,
} from './activitySlice';

/** A chat's states, most urgent first; the tile shows only the first. */
export type ConversationState =
  'failed' | 'needsYou' | 'working' | 'unread' | 'watching';

const DOT: Record<Exclude<ConversationState, 'working'>, string> = {
  failed: 'bg-destructive',
  needsYou: 'bg-warning',
  unread: 'bg-primary',
  // Hollow: something is on, nothing to do.
  watching: 'border-muted-foreground border-[1.5px]',
};

/** Every state a chat is in, most urgent first. */
export function useConversationStates(
  conversationId: string,
): ConversationState[] {
  const failed = useSelector(selectFailedConversations).has(conversationId);
  const needsYou = useSelector(selectApprovalConversations).has(conversationId);
  const working = useSelector(selectWorkingConversations).has(conversationId);
  const unread = useSelector(selectIsUnread(conversationId));
  const watching = useSelector((state: RootState) =>
    selectIsWatching(state, conversationId),
  );
  const states: ConversationState[] = [];
  if (failed) states.push('failed');
  if (needsYou) states.push('needsYou');
  if (working) states.push('working');
  if (unread && !failed) states.push('unread');
  if (watching) states.push('watching');
  return states;
}

/**
 * The one status mark on a sidebar chat: a red dot when something failed, an
 * amber dot while it waits for an approval, a spinner while it works, a brand
 * dot when there is something new, and a hollow ring while it watches
 * something. Every mark sits in the same 16px slot so their centres line up;
 * the tooltip names every state the chat is in.
 */
export default function ConversationMark({
  conversationId,
}: {
  conversationId: string;
}) {
  const { t } = useTranslation();
  const states = useConversationStates(conversationId);
  if (states.length === 0) return null;
  const top = states[0];
  const label = states.map((state) => t(`activity.marks.${state}`)).join(' · ');

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          role="img"
          aria-label={label}
          data-testid="conversation-mark"
          data-state={top}
          className="grid size-4 shrink-0 place-items-center"
        >
          {top === 'working' ? (
            <Spinner size="xs" className="text-primary" aria-hidden />
          ) : (
            <span aria-hidden className={cn('size-2 rounded-full', DOT[top])} />
          )}
        </span>
      </TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}
