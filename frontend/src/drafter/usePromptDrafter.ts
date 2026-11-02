import { useCallback, useMemo, useRef, useState } from 'react';

import {
  applyPromptEdits,
  type PromptImproveProposal,
  readPromptProposal,
} from './promptDraft';
import { type DraftedFields, useDraftedFields } from './useDraftedFields';
import { type DrafterSession, useDrafterSession } from './useDrafterSession';

export type PromptDecision = 'accepted' | 'rejected';

/** An improve proposal under review: the text it was made for and the choices so far. */
export type PromptReview = {
  proposal: PromptImproveProposal;
  original: string;
  decisions: Record<string, PromptDecision>;
  /** The change "Review one by one" is on; null before it starts. */
  current: string | null;
};

export type PromptDrafterOptions = {
  mode: 'improve' | 'write';
  promptId: string | null;
  name: string;
  content: string;
  setName: (name: string) => void;
  setContent: (content: string) => void;
};

export type PromptDrafter = {
  session: DrafterSession;
  review: PromptReview | null;
  drafted: DraftedFields<'name' | 'content'>;
  /** Accept or reject one change (null clears the choice). */
  decide: (id: string, decision: PromptDecision | null) => void;
  acceptAll: () => void;
  /** Start stepping through the changes from the first one left. */
  reviewOneByOne: () => void;
  /** Leave the review with the text as it was. */
  discard: () => void;
  /** Forget the conversation, the review and the marks. */
  reset: () => void;
};

/**
 * The prompt drafter (the prompt view's drawer in Settings › Prompts): it
 * sends the prompt with each request, turns
 * an improve proposal into a review whose accepted changes write into the
 * text as they are chosen, and fills a written prompt's text (and its name
 * when empty), each marked Drafted with undo. A request while a review is
 * open ends the review with the choices so far. Nothing is saved: the
 * host's Save still does that.
 *
 * Args:
 *   options: The mode and the prompt's current values and setters.
 *
 * Returns:
 *   The session for the drawer and the review state with its actions.
 */
export function usePromptDrafter(options: PromptDrafterOptions): PromptDrafter {
  const latest = useRef(options);
  latest.current = options;
  // The text the running turn was sent with: a proposal's edits fit it.
  const sent = useRef('');
  const [review, setReview] = useState<PromptReview | null>(null);

  const values = useMemo(
    () => ({ name: options.name, content: options.content }),
    [options.name, options.content],
  );
  const drafted = useDraftedFields<'name' | 'content'>(
    values,
    (field, previous) => {
      const value = typeof previous === 'string' ? previous : '';
      if (field === 'name') latest.current.setName(value);
      else latest.current.setContent(value);
    },
  );
  const draftedRef = useRef(drafted);
  draftedRef.current = drafted;
  const reviewRef = useRef(review);
  reviewRef.current = review;

  const getContext = useCallback(() => {
    const { mode, promptId, name, content } = latest.current;
    // A new request while a review is open (the drawer's ask bar stays
    // open) ends it with the choices made so far: the text already holds
    // them, and a change not chosen stays as it was.
    const open = reviewRef.current;
    if (open) {
      setReview(null);
      if (content !== open.original)
        draftedRef.current.mark('content', open.original, content);
    }
    sent.current = content;
    return { mode, prompt: { id: promptId, name, content }, agent: null };
  }, []);

  const onProposal = useCallback((raw: unknown) => {
    const proposal = readPromptProposal(raw);
    if (!proposal) return;
    if (proposal.mode === 'write') {
      const { name, content, setName, setContent } = latest.current;
      // A name the user typed stays; only an empty one is filled.
      if (!name.trim()) {
        setName(proposal.name);
        draftedRef.current.mark('name', name, proposal.name);
      }
      setContent(proposal.content);
      draftedRef.current.mark('content', content, proposal.content);
      return;
    }
    if (proposal.edits.length === 0) return;
    // The text is read-only while a turn runs, so it is still what was sent.
    setReview({
      proposal,
      original: sent.current,
      decisions: {},
      current: null,
    });
  }, []);

  const session = useDrafterSession({
    recipe: 'prompt',
    getContext,
    onProposal,
  });

  /** Write the review's text, and close it once every change is chosen. */
  const commit = useCallback(
    (next: PromptReview) => {
      const { proposal, original, decisions } = next;
      const content = applyPromptEdits(
        original,
        proposal.edits,
        (id) => decisions[id] === 'accepted',
      );
      latest.current.setContent(content);
      const done = proposal.edits.every((edit) => decisions[edit.id]);
      if (!done) {
        setReview(next);
        return;
      }
      setReview(null);
      if (content !== original) drafted.mark('content', original, content);
    },
    [drafted],
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
    latest.current.setContent(review.original);
    setReview(null);
  }, [review]);

  const resetSession = session.reset;
  const reset = useCallback(() => {
    resetSession();
    setReview(null);
    draftedRef.current.clear();
  }, [resetSession]);

  return {
    session,
    review,
    drafted,
    decide,
    acceptAll,
    reviewOneByOne,
    discard,
    reset,
  };
}
