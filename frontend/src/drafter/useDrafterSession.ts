import { useCallback, useEffect, useRef, useState } from 'react';
import { useSelector } from 'react-redux';

import { selectToken } from '../preferences/preferenceSlice';
import {
  DRAFTER_MAX_MESSAGES,
  DRAFTER_USER_MESSAGE_CHARS,
  type DrafterCounts,
  type DrafterErrorCode,
  type DrafterEvent,
  type DrafterMessage,
  type DrafterQuestion,
  type DrafterRecipe,
  streamDrafter,
} from './drafterApi';

/** One entry in the panel's conversation. */
export type DrafterItem =
  | { id: number; kind: 'user'; text: string }
  | { id: number; kind: 'status'; counts: DrafterCounts }
  | { id: number; kind: 'message'; text: string }
  | { id: number; kind: 'questions'; questions: DrafterQuestion[] }
  | { id: number; kind: 'proposal'; proposal: unknown }
  | { id: number; kind: 'error'; code: DrafterErrorCode; message?: string };

// Omit over each member of the union, so a push names one item's fields.
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown
  ? Omit<T, K>
  : never;
type NewItem = DistributiveOmit<DrafterItem, 'id'>;

/** What the panel shows while a turn runs. */
export type DrafterStep = 'thinking' | 'reading' | 'drafting';

export type DrafterSessionOptions = {
  recipe: DrafterRecipe;
  /** The recipe's `context`, read when each message is sent. */
  getContext: () => object;
  /** Called once for every proposal the drafter returns. */
  onProposal: (proposal: unknown) => void;
};

export type DrafterSession = {
  recipe: DrafterRecipe;
  items: DrafterItem[];
  /** The running turn's step; null while idle. */
  step: DrafterStep | null;
  streaming: boolean;
  /**
   * The history is as long as the server takes: a send does nothing until
   * `reset` starts over.
   */
  full: boolean;
  /**
   * Send a user message (a description, a change, composed answers).
   * `hidden` sends one the client composed ("Continue with Knowledge and
   * tools."): it runs the turn but draws no bubble and is not in
   * `userTexts`.
   */
  send: (text: string, options?: { hidden?: boolean }) => void;
  /** Add an assistant message the client wrote; the server never sees it. */
  addMessage: (text: string) => void;
  /** What the user wrote in this conversation, in order. */
  userTexts: () => string[];
  /** Stop the running turn; what arrived so far stays. */
  stop: () => void;
  /** Run the last turn again after an error. */
  retry: () => void;
  /** Start over with an empty conversation. */
  reset: () => void;
};

/**
 * The drafter's conversation, independent of the screen it fills: it keeps
 * the history the server needs (nothing is stored server-side), runs each
 * turn as an SSE stream, turns the events into panel items and hands every
 * proposal to `onProposal`. The history holds only answered turns: a failed,
 * stopped or replaced turn's message stays on screen but is not sent again
 * (Retry runs it once more), so the server never gets two user messages in a
 * row. Unmounting stops a running turn.
 *
 * Args:
 *   options: The recipe, a context getter and the proposal callback.
 *
 * Returns:
 *   The session the DraftPanel renders.
 */
export function useDrafterSession({
  recipe,
  getContext,
  onProposal,
}: DrafterSessionOptions): DrafterSession {
  const token = useSelector(selectToken);
  const [items, setItems] = useState<DrafterItem[]>([]);
  const [step, setStep] = useState<DrafterStep | null>(null);
  const [full, setFull] = useState(false);
  // Answered turns only: each user message with the drafter's answer.
  const history = useRef<DrafterMessage[]>([]);
  // The turn being answered: its message and the lines said so far.
  const pending = useRef<{ user: DrafterMessage; said: string[] } | null>(null);
  const userWords = useRef<string[]>([]);
  const controller = useRef<AbortController | null>(null);
  const nextId = useRef(0);
  // The latest callbacks, so a running turn never calls a stale one.
  const latest = useRef({ getContext, onProposal, token });
  latest.current = { getContext, onProposal, token };

  const push = useCallback((item: NewItem) => {
    nextId.current += 1;
    const id = nextId.current;
    setItems((prev) => [...prev, { ...item, id } as DrafterItem]);
  }, []);

  /** Close the pending turn with the drafter's answer, into the history. */
  const answer = useCallback((content: string) => {
    const turn = pending.current;
    if (!turn) return;
    pending.current = null;
    history.current.push(turn.user, { role: 'assistant', content });
    // The next send adds one message.
    setFull(history.current.length + 1 > DRAFTER_MAX_MESSAGES);
  }, []);

  /** A turn that only said something (a refusal, an explanation) is answered by it. */
  const answerWithWords = useCallback(() => {
    const said = pending.current?.said ?? [];
    if (said.length > 0) answer(said.join('\n\n'));
  }, [answer]);

  const handle = useCallback(
    (event: DrafterEvent) => {
      switch (event.type) {
        case 'status':
          if (event.step === 'reading') {
            setStep('reading');
            push({ kind: 'status', counts: event.counts ?? {} });
          } else setStep('drafting');
          return;
        case 'message':
          if (!event.text) return;
          pending.current?.said.push(event.text);
          push({ kind: 'message', text: event.text });
          return;
        case 'questions': {
          const said = pending.current?.said ?? [];
          answer(
            JSON.stringify(
              said.length > 0
                ? { ...event, message: said.join('\n\n') }
                : event,
            ),
          );
          push({ kind: 'questions', questions: event.questions ?? [] });
          return;
        }
        case 'proposal':
          answer(JSON.stringify(event));
          push({ kind: 'proposal', proposal: event.proposal });
          latest.current.onProposal(event.proposal);
          return;
        case 'error':
          push({ kind: 'error', code: event.code, message: event.message });
          return;
        case 'end':
          answerWithWords();
          setStep(null);
          return;
      }
    },
    [answer, answerWithWords, push],
  );

  const run = useCallback(() => {
    const turn = pending.current;
    if (!turn) return;
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setStep('thinking');
    void streamDrafter(
      {
        recipe,
        messages: [...history.current, turn.user],
        context: latest.current.getContext(),
      },
      latest.current.token,
      (event) => {
        if (controller.current === current) handle(event);
      },
      current.signal,
    ).finally(() => {
      if (controller.current === current) {
        controller.current = null;
        setStep(null);
      }
    });
  }, [handle, recipe]);

  const send = useCallback(
    (text: string, options?: { hidden?: boolean }) => {
      const message = text.trim().slice(0, DRAFTER_USER_MESSAGE_CHARS);
      if (!message || history.current.length + 1 > DRAFTER_MAX_MESSAGES) return;
      // A turn still pending (failed, stopped or running) gives way.
      pending.current = { user: { role: 'user', content: message }, said: [] };
      if (!options?.hidden) {
        userWords.current.push(message);
        push({ kind: 'user', text: message });
      }
      run();
    },
    [push, run],
  );

  const addMessage = useCallback(
    (text: string) => push({ kind: 'message', text }),
    [push],
  );

  const userTexts = useCallback(() => [...userWords.current], []);

  const stop = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
    answerWithWords();
    setStep(null);
  }, [answerWithWords]);

  const retry = useCallback(() => {
    // The failed turn's error goes; its message is still pending.
    setItems((prev) =>
      prev.at(-1)?.kind === 'error' ? prev.slice(0, -1) : prev,
    );
    run();
  }, [run]);

  const reset = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
    history.current = [];
    pending.current = null;
    setFull(false);
    userWords.current = [];
    setItems([]);
    setStep(null);
  }, []);

  useEffect(() => () => controller.current?.abort(), []);

  return {
    recipe,
    items,
    step,
    streaming: step !== null,
    full,
    send,
    addMessage,
    userTexts,
    stop,
    retry,
    reset,
  };
}
