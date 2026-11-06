import { useCallback, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';

import { promptAsRead, readPromptProposal } from './promptDraft';
import type { DrafterStarter } from './starters';
import { type DraftedFields, useDraftedFields } from './useDraftedFields';
import { type DrafterSession, useDrafterSession } from './useDrafterSession';
import {
  type PromptDecision,
  type PromptReview,
  usePromptReview,
} from './usePromptReview';

export type { PromptDecision, PromptReview } from './usePromptReview';

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
  /** Send a starting point's text, with its id going along for the session. */
  start: (starter: DrafterStarter, text: string) => void;
  /** Send `text` and draft from here on without asking questions. */
  skipQuestions: (text: string) => void;
  review: PromptReview | null;
  drafted: DraftedFields<'name' | 'content'>;
  /** Accept or reject one change (null clears the choice). */
  decide: (id: string, decision: PromptDecision | null) => void;
  acceptAll: () => void;
  /** Start stepping through the changes from the first one left. */
  reviewOneByOne: () => void;
  /** Leave the review with the text as it was. */
  discard: () => void;
  /**
   * A fresh conversation (the drawer's Start over): an open review ends with
   * the choices so far, and the text and its Drafted marks stay.
   */
  startOver: () => void;
  /** Forget the conversation, the review and the marks. */
  reset: () => void;
};

/**
 * The prompt drafter (the prompt view's drawer in Settings › Prompts): it
 * sends the prompt with each request, turns
 * an improve proposal into a review whose accepted changes write into the
 * text as they are chosen (those that fit the text as the server read it; a
 * message says so when none do), and fills a written prompt's text (and its name
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
  const { t } = useTranslation();
  const latest = useRef(options);
  latest.current = options;
  const tRef = useRef(t);
  tRef.current = t;
  // The session, for a message from a proposal it delivered.
  const sessionRef = useRef<DrafterSession | null>(null);
  // The text the running turn was sent with: a proposal's edits fit it.
  const sent = useRef('');
  // The starting point picked and a Skip on questions hold for the session.
  const starter = useRef<DrafterStarter | null>(null);
  const skipped = useRef(false);

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
  const reviews = usePromptReview(
    (content) => latest.current.setContent(content),
    drafted,
  );
  const reviewsRef = useRef(reviews);
  reviewsRef.current = reviews;

  const getContext = useCallback(() => {
    const { mode, promptId, name, content } = latest.current;
    // A new request while a review is open (the drawer's ask bar stays
    // open) ends it with the choices made so far: the text already holds
    // them, and a change not chosen stays as it was.
    reviewsRef.current.finish(content);
    sent.current = content;
    return {
      mode,
      prompt: { id: promptId, name, content },
      starter: starter.current,
      skip_questions: skipped.current,
    };
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
    const sentText = sent.current;
    const reviewed = reviewsRef.current.start(
      proposal.edits,
      promptAsRead(sentText),
      sentText,
    );
    if (reviewed === 0)
      sessionRef.current?.addMessage(
        tRef.current('drafter.agent.prompt.editsStale'),
      );
  }, []);

  const session = useDrafterSession({
    recipe: 'prompt',
    getContext,
    onProposal,
  });
  sessionRef.current = session;

  const send = session.send;
  const start = useCallback(
    (picked: DrafterStarter, text: string) => {
      starter.current = picked;
      send(text);
    },
    [send],
  );
  const skipQuestions = useCallback(
    (text: string) => {
      skipped.current = true;
      send(text);
    },
    [send],
  );

  const resetSession = session.reset;
  const startOver = useCallback(() => {
    starter.current = null;
    skipped.current = false;
    resetSession();
    reviewsRef.current.finish(latest.current.content);
  }, [resetSession]);
  const reset = useCallback(() => {
    starter.current = null;
    skipped.current = false;
    resetSession();
    reviewsRef.current.clear();
    draftedRef.current.clear();
  }, [resetSession]);

  return {
    session,
    start,
    skipQuestions,
    review: reviews.review,
    drafted,
    decide: reviews.decide,
    acceptAll: reviews.acceptAll,
    reviewOneByOne: reviews.reviewOneByOne,
    discard: reviews.discard,
    startOver,
    reset,
  };
}
