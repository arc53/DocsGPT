import { useCallback, useRef, useState } from 'react';

import { applyPromptEdits, fittingEdits, type PromptEdit } from './promptDraft';
import type { DraftedFields } from './useDraftedFields';

export type PromptDecision = 'accepted' | 'rejected';

/** Edits under review: the text they were made for and the choices so far. */
export type PromptReview = {
  proposal: { edits: PromptEdit[] };
  original: string;
  /**
   * The text as it stood, put back while no change is accepted; it can
   * differ from `original` in its line ends. `original` when left out.
   */
  before?: string;
  decisions: Record<string, PromptDecision>;
  /** The change "Review one by one" is on; null before it starts. */
  current: string | null;
};

export type PromptReviewState = {
  review: PromptReview | null;
  /**
   * Open a review of the `edits` that fit `original` (the text now, as the
   * drafter read it; `before` when that differs from the field's text).
   * Returns how many changes are under review: 0 opens none.
   */
  start: (edits: PromptEdit[], original: string, before?: string) => number;
  /** Accept or reject one change (null clears the choice). */
  decide: (id: string, decision: PromptDecision | null) => void;
  acceptAll: () => void;
  /** Start stepping through the changes from the first one left. */
  reviewOneByOne: () => void;
  /** Leave the review with the text as it was. */
  discard: () => void;
  /**
   * End the review with the choices so far (a new request does): the text
   * already holds them, marked Drafted when it changed.
   */
  finish: (content: string) => void;
  /** Drop the review, leaving the text as it stands. */
  clear: () => void;
};

/**
 * Accept / Reject review of a prompt's edits, shared by the prompt drawer
 * and the agent form's prompt view: each choice writes the text at once,
 * and once every change is chosen the review closes and a changed text is
 * marked Drafted with undo. Only changes that fit the text are reviewed, so
 * every one the review waits on is shown.
 *
 * Args:
 *   setContent: Writes the prompt's text.
 *   drafted: The prompt's Drafted marks.
 *
 * Returns:
 *   The review and its actions.
 */
export function usePromptReview(
  setContent: (content: string) => void,
  drafted: DraftedFields<'name' | 'content'>,
): PromptReviewState {
  const [review, setReview] = useState<PromptReview | null>(null);
  const latest = useRef({ setContent, drafted });
  latest.current = { setContent, drafted };
  const reviewRef = useRef(review);
  reviewRef.current = review;

  /** Write the review's text, and close it once every change is chosen. */
  const commit = useCallback((next: PromptReview) => {
    const { proposal, original, decisions } = next;
    const before = next.before ?? original;
    const accepted = (id: string) => decisions[id] === 'accepted';
    const content = proposal.edits.some((edit) => accepted(edit.id))
      ? applyPromptEdits(original, proposal.edits, accepted)
      : before;
    latest.current.setContent(content);
    const done = proposal.edits.every((edit) => decisions[edit.id]);
    if (!done) {
      setReview(next);
      return;
    }
    setReview(null);
    if (content !== before)
      latest.current.drafted.mark('content', before, content);
  }, []);

  const start = useCallback(
    (edits: PromptEdit[], original: string, before?: string) => {
      const fitting = fittingEdits(original, edits);
      if (fitting.length > 0)
        setReview({
          proposal: { edits: fitting },
          original,
          ...(before !== undefined && before !== original && { before }),
          decisions: {},
          current: null,
        });
      return fitting.length;
    },
    [],
  );

  const decide = useCallback(
    (id: string, decision: PromptDecision | null) => {
      if (!review) return;
      const decisions = { ...review.decisions };
      if (decision) decisions[id] = decision;
      else delete decisions[id];
      const edits = review.proposal.edits;
      let current = review.current;
      if (current !== null && decision) {
        // One by one: on to the next change still open, after this one.
        const from = edits.findIndex((edit) => edit.id === id);
        const order = [...edits.slice(from + 1), ...edits.slice(0, from)];
        current = order.find((edit) => !decisions[edit.id])?.id ?? null;
      }
      commit({ ...review, decisions, current });
    },
    [commit, review],
  );

  const acceptAll = useCallback(() => {
    if (!review) return;
    const decisions = { ...review.decisions };
    review.proposal.edits.forEach((edit) => {
      decisions[edit.id] ??= 'accepted';
    });
    commit({ ...review, decisions });
  }, [commit, review]);

  const reviewOneByOne = useCallback(() => {
    setReview((prev) =>
      prev
        ? {
            ...prev,
            current:
              prev.proposal.edits.find((edit) => !prev.decisions[edit.id])
                ?.id ?? null,
          }
        : prev,
    );
  }, []);

  const discard = useCallback(() => {
    if (!review) return;
    latest.current.setContent(review.before ?? review.original);
    setReview(null);
  }, [review]);

  const finish = useCallback((content: string) => {
    const open = reviewRef.current;
    if (!open) return;
    setReview(null);
    const before = open.before ?? open.original;
    if (content !== before)
      latest.current.drafted.mark('content', before, content);
  }, []);

  const clear = useCallback(() => setReview(null), []);

  return {
    review,
    start,
    decide,
    acceptAll,
    reviewOneByOne,
    discard,
    finish,
    clear,
  };
}
