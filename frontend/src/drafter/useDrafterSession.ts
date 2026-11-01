import { useCallback, useEffect, useRef, useState } from 'react';
import { useSelector } from 'react-redux';

import { selectToken } from '../preferences/preferenceSlice';
import {
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
  /** Send a user message (a description, a change, composed answers). */
  send: (text: string) => void;
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
 * proposal to `onProposal`. Unmounting stops a running turn.
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
  const history = useRef<DrafterMessage[]>([]);
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
          if (event.text) push({ kind: 'message', text: event.text });
          return;
        case 'questions':
          history.current.push({
            role: 'assistant',
            content: JSON.stringify(event),
          });
          push({ kind: 'questions', questions: event.questions ?? [] });
          return;
        case 'proposal':
          history.current.push({
            role: 'assistant',
            content: JSON.stringify(event),
          });
          push({ kind: 'proposal', proposal: event.proposal });
          latest.current.onProposal(event.proposal);
          return;
        case 'error':
          push({ kind: 'error', code: event.code, message: event.message });
          return;
        case 'end':
          setStep(null);
          return;
      }
    },
    [push],
  );

  const run = useCallback(() => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setStep('thinking');
    void streamDrafter(
      {
        recipe,
        messages: [...history.current],
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
    (text: string) => {
      const message = text.trim();
      if (!message) return;
      history.current.push({ role: 'user', content: message });
      push({ kind: 'user', text: message });
      run();
    },
    [push, run],
  );

  const stop = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
    setStep(null);
  }, []);

  const retry = useCallback(() => {
    // The failed turn's error goes; the history still ends with the turn.
    setItems((prev) =>
      prev.at(-1)?.kind === 'error' ? prev.slice(0, -1) : prev,
    );
    run();
  }, [run]);

  const reset = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
    history.current = [];
    setItems([]);
    setStep(null);
  }, []);

  useEffect(() => () => controller.current?.abort(), []);

  return {
    recipe,
    items,
    step,
    streaming: step !== null,
    send,
    stop,
    retry,
    reset,
  };
}
