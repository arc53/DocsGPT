import { useCallback, useEffect, useRef, useState } from 'react';
import { useSelector } from 'react-redux';

import { selectToken } from '../preferences/preferenceSlice';
import {
  cancelDrafterTurn,
  DRAFTER_MAX_MESSAGES,
  DRAFTER_USER_MESSAGE_CHARS,
  type DrafterCounts,
  type DrafterErrorCode,
  type DrafterEvent,
  type DrafterMessage,
  type DrafterQuestion,
  type DrafterRecipe,
  newDrafterTurnId,
  streamDrafter,
} from './drafterApi';

/** One entry in the panel's conversation. */
export type DrafterItem =
  | { id: number; kind: 'user'; text: string }
  | { id: number; kind: 'status'; counts: DrafterCounts }
  | { id: number; kind: 'message'; text: string }
  /** The example questions the turn read, all its reads in one item. */
  | { id: number; kind: 'read'; items: string[] }
  /**
   * A round of questions: open until a message passes it, then its record:
   * `answered` (with each question's answer as text, by id), `skipped`, or
   * `passed` (a message went past it unanswered).
   */
  | {
      id: number;
      kind: 'questions';
      questions: DrafterQuestion[];
      state?: QuestionsState;
      answers?: Record<string, string>;
    }
  | { id: number; kind: 'proposal'; proposal: unknown }
  | { id: number; kind: 'error'; code: DrafterErrorCode; message?: string };

// Omit over each member of the union, so a push names one item's fields.
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown
  ? Omit<T, K>
  : never;
type NewItem = DistributiveOmit<DrafterItem, 'id'>;

/** How a round of questions closed. */
export type QuestionsState = 'answered' | 'skipped' | 'passed';

/** How a message goes out (`send`'s options). */
export type DrafterSendOptions = {
  /**
   * A message the client composed ("Continue with Knowledge and tools."): it
   * runs the turn but draws no bubble and is not in `userTexts`.
   */
  hidden?: boolean;
  /**
   * The message answers the open questions: each question's answer as text,
   * by id. It draws no bubble (the answered cards are the record) but stays
   * in `userTexts`.
   */
  answers?: Record<string, string>;
};

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
   * Send a user message (a description, a change, composed answers). Any
   * message closes the open questions: `answers` as answered, otherwise as
   * passed. See DrafterSendOptions for `hidden`.
   */
  send: (text: string, options?: DrafterSendOptions) => void;
  /** Close the open questions without answers (Skip and draft). */
  closeQuestions: (state: 'skipped') => void;
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
 * row. Unmounting stops a running turn. A turn given up on (Stop, Start over,
 * a new message, unmounting, a broken stream) is also cancelled on the server,
 * which otherwise runs it to its end.
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
  // The running turn's id until it ends: the one the request sent, so a Stop
  // before the `turn` event still reaches it, or the one that event carried.
  const turnId = useRef<string | null>(null);
  // The current attempt failed: its words are no answer, and Retry runs it again.
  const failed = useRef(false);
  const nextId = useRef(0);
  // The latest callbacks, so a running turn never calls a stale one.
  const latest = useRef({ getContext, onProposal, token });
  latest.current = { getContext, onProposal, token };

  // The running attempt's `read` item, which its later reads add to.
  const readItem = useRef<number | null>(null);

  const push = useCallback((item: NewItem) => {
    nextId.current += 1;
    const id = nextId.current;
    setItems((prev) => [...prev, { ...item, id } as DrafterItem]);
    return id;
  }, []);

  /** Add what a read showed to the turn's one `read` item, without repeats. */
  const addRead = useCallback(
    (questions: string[]) => {
      const id = readItem.current;
      if (id === null) {
        readItem.current = push({
          kind: 'read',
          items: [...new Set(questions)],
        });
        return;
      }
      setItems((prev) =>
        prev.map((item) =>
          item.id === id && item.kind === 'read'
            ? { ...item, items: [...new Set([...item.items, ...questions])] }
            : item,
        ),
      );
    },
    [push],
  );

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
    if (failed.current) return;
    const said = pending.current?.said ?? [];
    if (said.length > 0) answer(said.join('\n\n'));
  }, [answer]);

  /** Cancel the server's turn, which a dropped stream doesn't stop. */
  const cancelTurn = useCallback(() => {
    const id = turnId.current;
    turnId.current = null;
    if (id) void cancelDrafterTurn(id, latest.current.token);
  }, []);

  /** Give up on the running turn: drop its stream and cancel it on the server. */
  const abort = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
    cancelTurn();
  }, [cancelTurn]);

  const handle = useCallback(
    (event: DrafterEvent) => {
      switch (event.type) {
        case 'turn':
          turnId.current = event.id;
          return;
        case 'status':
          if (event.step === 'reading') {
            setStep('reading');
            push({ kind: 'status', counts: event.counts ?? {} });
          } else setStep('drafting');
          return;
        case 'read':
          if (event.items.length > 0) addRead(event.items);
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
          failed.current = true;
          push({ kind: 'error', code: event.code, message: event.message });
          return;
        case 'end':
          // After an error the turn stays pending for Retry. The server may still
          // be running it (the stream broke off), so it is cancelled.
          if (failed.current) cancelTurn();
          else answerWithWords();
          turnId.current = null;
          setStep(null);
          return;
      }
    },
    [addRead, answer, answerWithWords, cancelTurn, push],
  );

  const run = useCallback(() => {
    const turn = pending.current;
    if (!turn) return;
    abort();
    // A new attempt: what a failed one said is not part of its answer.
    failed.current = false;
    turn.said = [];
    readItem.current = null;
    const current = new AbortController();
    controller.current = current;
    const id = newDrafterTurnId();
    turnId.current = id;
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
      id,
    ).finally(() => {
      if (controller.current === current) {
        controller.current = null;
        setStep(null);
      }
    });
  }, [abort, handle, recipe]);

  /** Close every open round: the latest with `answers` when given. */
  const close = useCallback(
    (state: QuestionsState, answers?: Record<string, string>) =>
      setItems((prev) => {
        const latestOpen = prev.findLastIndex(
          (item) => item.kind === 'questions' && !item.state,
        );
        if (latestOpen < 0) return prev;
        return prev.map((item, index) => {
          if (item.kind !== 'questions' || item.state) return item;
          return index === latestOpen && answers
            ? { ...item, state, answers }
            : { ...item, state: state === 'answered' ? 'passed' : state };
        });
      }),
    [],
  );

  const closeQuestions = useCallback(
    (state: 'skipped') => close(state),
    [close],
  );

  const send = useCallback(
    (text: string, options?: DrafterSendOptions) => {
      const message = text.trim().slice(0, DRAFTER_USER_MESSAGE_CHARS);
      if (!message || history.current.length + 1 > DRAFTER_MAX_MESSAGES) return;
      // A turn still pending (failed, stopped or running) gives way.
      pending.current = { user: { role: 'user', content: message }, said: [] };
      close(options?.answers ? 'answered' : 'passed', options?.answers);
      if (!options?.hidden) userWords.current.push(message);
      if (!options?.hidden && !options?.answers)
        push({ kind: 'user', text: message });
      run();
    },
    [close, push, run],
  );

  const addMessage = useCallback(
    (text: string) => push({ kind: 'message', text }),
    [push],
  );

  const userTexts = useCallback(() => [...userWords.current], []);

  const stop = useCallback(() => {
    abort();
    answerWithWords();
    setStep(null);
  }, [abort, answerWithWords]);

  const retry = useCallback(() => {
    // The failed turn's error goes; its message is still pending.
    setItems((prev) =>
      prev.at(-1)?.kind === 'error' ? prev.slice(0, -1) : prev,
    );
    run();
  }, [run]);

  const reset = useCallback(() => {
    abort();
    history.current = [];
    pending.current = null;
    setFull(false);
    userWords.current = [];
    setItems([]);
    setStep(null);
  }, [abort]);

  useEffect(() => () => abort(), [abort]);

  return {
    recipe,
    items,
    step,
    streaming: step !== null,
    full,
    send,
    closeQuestions,
    addMessage,
    userTexts,
    stop,
    retry,
    reset,
  };
}
