import { describe, expect, it, vi } from 'vitest';

// The streaming path is chosen when the slice module loads.
vi.hoisted(() => {
  window.__DOCSGPT_ENV__ = { VITE_API_STREAMING: 'true' };
});

vi.mock('./conversationHandlers', () => ({
  handleFetchAnswer: vi.fn(),
  handleFetchAnswerSteaming: vi.fn(),
  handleSubmitToolActions: vi.fn(),
  handleV1ChatCompletionStreaming: vi.fn(),
}));

import { configureStore } from '@reduxjs/toolkit';

import conversationService from '../api/services/conversationService';
import uploadReducer from '../upload/uploadSlice';
import { handleFetchAnswerSteaming } from './conversationHandlers';
import reducer, { addQuery, fetchAnswer } from './conversationSlice';

const preference = {
  token: 'tok',
  selectedDocs: [],
  prompt: { id: 'default' },
  selectedAgent: null,
  selectedModel: null,
};

const makeStore = () =>
  configureStore({
    reducer: {
      conversation: reducer,
      upload: uploadReducer,
      preference: () => preference,
    },
  });

const event = (data: object) =>
  new MessageEvent('message', { data: JSON.stringify(data) });

/** The live stream started, then the client lost it for good. */
function lostAfterStart(lost: object) {
  vi.mocked(handleFetchAnswerSteaming).mockImplementation(
    async (_q, _signal, _token, _docs, _conv, _prompt, onEvent) => {
      onEvent(
        event({
          type: 'message_id',
          message_id: 'm-1',
          conversation_id: 'c-1',
        }),
      );
      onEvent(event({ type: 'answer', answer: 'Part' }));
      onEvent(event({ type: 'error', error: 'Connection lost.', ...lost }));
      return undefined as never;
    },
  );
}

describe('a chat stream this client lost', () => {
  it('follows the answer the server is still writing instead of failing the turn', async () => {
    lostAfterStart({ code: 'connection_lost', message_id: 'm-1' });
    const tail = vi
      .spyOn(conversationService, 'tailMessage')
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          message_id: 'm-1',
          status: 'complete',
          response: 'Part of the answer, finished.',
        }),
      } as Response);
    const store = makeStore();
    store.dispatch(addQuery({ prompt: 'q' }));

    await store.dispatch(fetchAnswer({ question: 'q' }));
    await vi.waitFor(() =>
      expect(store.getState().conversation.status).toBe('idle'),
    );

    expect(tail).toHaveBeenCalledWith('m-1', 'tok');
    const turn = store.getState().conversation.queries[0];
    expect(turn.response).toBe('Part of the answer, finished.');
    expect(turn.error).toBeUndefined();
    tail.mockRestore();
  });

  it('still fails the turn when it cannot tell which message it lost', async () => {
    lostAfterStart({ code: 'connection_lost' });
    const tail = vi.spyOn(conversationService, 'tailMessage');
    const store = makeStore();
    store.dispatch(addQuery({ prompt: 'q' }));

    await store.dispatch(fetchAnswer({ question: 'q' }));

    expect(tail).not.toHaveBeenCalled();
    expect(store.getState().conversation.status).toBe('failed');
    expect(store.getState().conversation.queries[0].error).toBe(
      'Connection lost.',
    );
    tail.mockRestore();
  });
});
