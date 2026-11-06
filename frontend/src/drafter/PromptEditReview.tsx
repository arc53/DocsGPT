import { useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn, fieldFrame, focusRing } from '@/lib/utils';

import { promptDiffSegments, type PromptEdit } from './promptDraft';
import type { PromptDecision, PromptReview } from './usePromptReview';

/**
 * An improve proposal under review, in place of the prompt's textarea: the
 * text with each change inline (the removed passage struck through in muted
 * text, the new one on the brand tint), numbered, and below it the list of
 * changes with their reasons and Accept / Reject each. "Review one by one"
 * (the drawer's turn) marks the change being decided
 * and moves on after each choice. Accept all and Discard there finish the
 * review.
 *
 * Args:
 *   review: The proposal, the text it was made for and the choices so far.
 *   onDecide: Accept or reject a change; null takes a choice back.
 */
export function PromptEditReview({
  review,
  onDecide,
}: {
  review: PromptReview;
  onDecide: (id: string, decision: PromptDecision | null) => void;
}) {
  const { t } = useTranslation();
  const { proposal, original, decisions, current } = review;
  const segments = useMemo(
    () => promptDiffSegments(original, proposal.edits),
    [original, proposal.edits],
  );
  const changes = segments.flatMap((segment) =>
    segment.kind === 'change' ? [segment] : [],
  );
  const textRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLOListElement>(null);

  // One by one: bring the current change into view, and its Accept to hand.
  useEffect(() => {
    if (!current) return;
    textRef.current
      ?.querySelector(`[data-edit-id="${current}"]`)
      ?.scrollIntoView?.({ block: 'nearest' });
    listRef.current
      ?.querySelector<HTMLButtonElement>(
        `[data-change-id="${current}"] [data-action="accept"]`,
      )
      ?.focus();
  }, [current]);

  const renderChange = (edit: PromptEdit, number: number) => {
    const decision = decisions[edit.id];
    return (
      <span
        key={edit.id}
        data-edit-id={edit.id}
        data-decision={decision}
        data-current={current === edit.id || undefined}
        // An underline, not a ring: a change can wrap over several lines.
        className={cn(
          current === edit.id &&
            'decoration-primary underline decoration-2 underline-offset-4',
        )}
      >
        <sup className="text-link px-0.5 text-xs font-semibold">{number}</sup>
        {decision === 'rejected' ? (
          edit.find
        ) : (
          <>
            {decision !== 'accepted' && edit.find && (
              <del className="text-muted-foreground line-through">
                <span className="sr-only">
                  {t('drafter.prompt.removedText')}
                </span>
                {edit.find}
              </del>
            )}
            {edit.replace && (
              <ins className="bg-secondary text-foreground rounded-sm no-underline">
                <span className="sr-only">{t('drafter.prompt.addedText')}</span>
                {edit.replace}
              </ins>
            )}
          </>
        )}
      </span>
    );
  };

  return (
    <div data-slot="prompt-review" className="flex flex-col gap-3">
      <div
        ref={textRef}
        role="region"
        aria-label={t('drafter.prompt.reviewLabel')}
        tabIndex={0}
        className={cn(
          focusRing,
          fieldFrame,
          'bg-background focus-visible:border-ring scrollbar-overlay max-h-[35dvh] min-h-32 overflow-y-auto rounded-2xl px-4 py-3 text-base wrap-break-word whitespace-pre-wrap md:text-sm',
        )}
      >
        {segments.map((segment, index) =>
          segment.kind === 'text' ? (
            <span key={`t${index}`}>{segment.text}</span>
          ) : (
            renderChange(segment.edit, segment.number)
          ),
        )}
      </div>
      <ol ref={listRef} className="flex flex-col gap-1">
        {changes.map(({ edit, number }) => {
          const decision = decisions[edit.id];
          return (
            <li
              key={edit.id}
              data-change-id={edit.id}
              className={cn(
                'flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-3 py-2',
                current === edit.id && 'bg-secondary',
              )}
            >
              <span className="text-link text-sm font-semibold">{number}</span>
              <p className="min-w-0 flex-1 text-sm">{edit.reason}</p>
              {decision ? (
                <span className="flex items-center gap-2">
                  <Badge
                    variant={decision === 'accepted' ? 'success' : 'neutral'}
                  >
                    {t(`drafter.prompt.${decision}`)}
                  </Badge>
                  <Button
                    type="button"
                    variant="link"
                    size="inline"
                    aria-label={t('drafter.prompt.undoChoiceLabel', {
                      number,
                    })}
                    onClick={() => onDecide(edit.id, null)}
                  >
                    {t('drafter.prompt.undoChoice')}
                  </Button>
                </span>
              ) : (
                <span className="flex items-center gap-1">
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    shape="pill"
                    data-action="accept"
                    aria-label={t('drafter.prompt.acceptChange', { number })}
                    onClick={() => onDecide(edit.id, 'accepted')}
                  >
                    {t('drafter.prompt.accept')}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="xs"
                    shape="pill"
                    data-action="reject"
                    aria-label={t('drafter.prompt.rejectChange', { number })}
                    onClick={() => onDecide(edit.id, 'rejected')}
                  >
                    {t('drafter.prompt.reject')}
                  </Button>
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
