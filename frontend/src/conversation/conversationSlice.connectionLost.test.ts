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
import {
  handleFetchAnswerSteaming,
  handleSubmitToolActions,
} from './conversationHandlers';
import reducer, {
  addQuery,
  fetchAnswer,
  setConversation,
  setConversationId,
  setStatus,
  submitToolActions,
  tailInFlightMessage,
} from './conversationSlice';

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

describe('a tool-actions stream this client lost', () => {
  it('follows the resumed turn instead of failing it', async () => {
    vi.mocked(handleSubmitToolActions).mockImplementation(
      async (_conversationId, _actions, _token, _signal, onEvent) => {
        onEvent(event({ type: 'message_id', message_id: 'm-1' }));
        onEvent(event({ type: 'answer', answer: 'Sent' }));
        onEvent(
          event({
            type: 'error',
            error: 'Connection lost.',
            code: 'connection_lost',
            message_id: 'm-1',
          }),
        );
        return undefined as never;
      },
    );
    const tail = vi
      .spyOn(conversationService, 'tailMessage')
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          message_id: 'm-1',
          status: 'complete',
          response: 'Sent the email.',
        }),
      } as Response);
    const store = makeStore();
    store.dispatch(setConversation([{ prompt: 'send it', messageId: 'm-1' }]));
    store.dispatch(setConversationId('c-1'));
    store.dispatch(setStatus('awaiting_tool_actions'));

    await store.dispatch(
      submitToolActions({
        toolActions: [{ call_id: 'call-1', decision: 'approved' }],
      }),
    );
    await vi.waitFor(() =>
      expect(store.getState().conversation.status).toBe('idle'),
    );

    expect(tail).toHaveBeenCalledWith('m-1', 'tok');
    const turn = store.getState().conversation.queries[0];
    expect(turn.response).toBe('Sent the email.');
    expect(turn.error).toBeUndefined();
    tail.mockRestore();
  });
});

describe('following a message by polling', () => {
  it('leaves another chat alone when the user opened it during the request', async () => {
    const store = makeStore();
    store.dispatch(setConversation([{ prompt: 'q', messageId: 'm-1' }]));
    store.dispatch(setConversationId('c-1'));
    const tail = vi
      .spyOn(conversationService, 'tailMessage')
      .mockImplementationOnce(async () => {
        // The user switches chats while the request is out.
        store.dispatch(
          setConversation([{ prompt: 'other', messageId: 'm-2' }]),
        );
        store.dispatch(setConversationId('c-2'));
        store.dispatch(setStatus('loading'));
        return {
          ok: true,
          status: 200,
          json: async () => ({
            message_id: 'm-1',
            status: 'complete',
            response: 'stale',
          }),
        } as Response;
      });

    await store.dispatch(
      tailInFlightMessage({
        messageId: 'm-1',
        index: 0,
        conversationId: 'c-1',
      }),
    );

    const { queries, status } = store.getState().conversation;
    expect(queries[0].response).toBeUndefined();
    expect(status).toBe('loading');
    tail.mockRestore();
  });
});
