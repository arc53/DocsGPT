import { describe, expect, it, vi } from 'vitest';

// The preview streams, as a deployment does.
vi.mock('@/env', () => ({
  envVar: (name: string) => (name === 'VITE_API_STREAMING' ? 'true' : ''),
}));
vi.mock('../conversation/conversationHandlers', () => ({
  handleFetchAnswer: vi.fn(),
  handleFetchAnswerSteaming: vi.fn(),
  handleSubmitToolActions: vi.fn(),
}));

import { configureStore } from '@reduxjs/toolkit';

import {
  handleFetchAnswerSteaming,
  handleSubmitToolActions,
} from '../conversation/conversationHandlers';
import reducer, {
  addQuery,
  fetchPreviewAnswer,
  raiseError,
  resumePreviewQuestion,
} from './agentPreviewSlice';

describe('agent preview curated errors', () => {
  const seeded = () => reducer(undefined, addQuery({ prompt: 'q' }));

  it('keeps the code and params of a curated error', () => {
    const next = reducer(
      seeded(),
      raiseError({
        index: 0,
        message: 'Too large.',
        code: 'context_length_exceeded',
        params: { needed_tokens: 300000, available_tokens: 200000 },
      }),
    );
    expect(next.queries[0].error).toBe('Too large.');
    expect(next.queries[0].errorCode).toBe('context_length_exceeded');
    expect(next.queries[0].errorParams).toEqual({
      needed_tokens: 300000,
      available_tokens: 200000,
    });
  });

  it('drops a stale code when a later error has none', () => {
    let state = reducer(
      seeded(),
      raiseError({ index: 0, message: 'x', code: 'server_error' }),
    );
    state = reducer(state, raiseError({ index: 0, message: 'raw' }));
    expect(state.queries[0].errorCode).toBeUndefined();
    expect(state.queries[0].errorParams).toBeUndefined();
  });
});

describe('agent preview questions', () => {
  const event = (data: object) =>
    new MessageEvent('message', { data: JSON.stringify(data) });
  const makeStore = () =>
    configureStore({
      reducer: {
        agentPreview: reducer,
        preference: () => ({
          token: 'tok',
          selectedDocs: [],
          prompt: { id: 'default' },
          chunks: '2',
          selectedAgent: { id: 'agent-1' },
          selectedModel: null,
        }),
        upload: () => ({ attachments: [] }),
      },
    });

  it('pauses on the questions and resumes in the turn’s conversation', async () => {
    const paused = {
      tool_name: 'ask_user',
      action_name: 'ask_user',
      call_id: 'ask-1',
      arguments: {},
      status: 'awaiting_answer',
      message: 'Which one?',
      questions: [{ id: 'q1', text: 'Which quarter?', options: [] }],
    };
    vi.mocked(handleFetchAnswerSteaming).mockImplementation(
      async (_q, _signal, _token, _docs, _conv, _prompt, _chunks, onEvent) => {
        onEvent(event({ type: 'tool_call', data: paused }));
        onEvent(event({ type: 'tool_calls_pending' }));
        onEvent(event({ type: 'id', id: 'conv-9' }));
        onEvent(event({ type: 'end' }));
        return undefined as never;
      },
    );
    vi.mocked(handleSubmitToolActions).mockResolvedValue(undefined as never);
    const store = makeStore();
    store.dispatch(addQuery({ prompt: 'write the deck' }));
    await store.dispatch(fetchPreviewAnswer({ question: 'write the deck' }));
    expect(store.getState().agentPreview.queries[0].conversationId).toBe(
      'conv-9',
    );

    await store.dispatch(
      resumePreviewQuestion({
        callId: 'ask-1',
        action: { answer: 'Which quarter? → Q3' },
      }),
    );
    const [conversationId, actions] = vi.mocked(handleSubmitToolActions).mock
      .calls[0];
    expect(conversationId).toBe('conv-9');
    expect(actions).toEqual([
      { call_id: 'ask-1', answer: 'Which quarter? → Q3' },
    ]);
    expect(
      store.getState().agentPreview.queries[0].tool_calls?.[0].status,
    ).toBe('success');
  });
});
