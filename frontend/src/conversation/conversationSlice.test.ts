import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./conversationHandlers', () => ({
  handleFetchAnswer: vi.fn().mockResolvedValue(null),
  handleFetchAnswerSteaming: vi.fn().mockResolvedValue(undefined),
  handleSubmitToolActions: vi.fn(),
  handleV1ChatCompletionStreaming: vi.fn(),
}));

import { configureStore } from '@reduxjs/toolkit';

import conversationService from '../api/services/conversationService';
import type { Agent } from '../agents/types';
import preferenceReducer, {
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import uploadReducer, { addAttachment } from '../upload/uploadSlice';
import { handleFetchAnswer } from './conversationHandlers';
import reducer, {
  addQuery,
  applyMessageTail,
  fetchAnswer,
  loadConversation,
  mapServerQueryToClient,
  raiseError,
  raiseNotice,
  resendQuery,
  setConversation,
} from './conversationSlice';

const baseQuery = {
  prompt: 'tell me a poem',
  messageId: 'm-1',
  messageStatus: 'pending' as const,
};

const seedSlice = () => reducer(undefined, setConversation([baseQuery]));

describe('applyMessageTail — streaming partial', () => {
  it('writes response to the query while status is streaming', () => {
    const state = seedSlice();
    const next = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'streaming',
          response: 'Hello, par',
          thought: null,
          sources: [],
          tool_calls: [],
        },
      }),
    );
    expect(next.queries[0].messageStatus).toBe('streaming');
    expect(next.queries[0].response).toBe('Hello, par');
  });

  it('updates response on each successive tail tick', () => {
    let state = seedSlice();
    state = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'streaming',
          response: 'Hello',
          sources: [],
          tool_calls: [],
        },
      }),
    );
    state = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'streaming',
          response: 'Hello, world',
          sources: [],
          tool_calls: [],
        },
      }),
    );
    expect(state.queries[0].response).toBe('Hello, world');
  });

  it('applies sources and tool_calls when they appear mid-stream', () => {
    const state = seedSlice();
    const next = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'streaming',
          response: 'partial',
          sources: [{ id: 's1', title: 'doc' }],
          tool_calls: [{ name: 'search' }],
        },
      }),
    );
    expect(next.queries[0].sources).toEqual([{ id: 's1', title: 'doc' }]);
    expect(next.queries[0].tool_calls).toEqual([{ name: 'search' }]);
  });

  it('ignores empty sources / tool_calls arrays so the renderer stays clean', () => {
    const state = seedSlice();
    const next = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'streaming',
          response: 'partial',
          sources: [],
          tool_calls: [],
        },
      }),
    );
    expect(next.queries[0].sources).toBeUndefined();
    expect(next.queries[0].tool_calls).toBeUndefined();
  });

  it('promotes to complete with the final response and clears any error', () => {
    let state = seedSlice();
    state = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'streaming',
          response: 'partial',
        },
      }),
    );
    state = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'complete',
          response: 'Final answer.',
        },
      }),
    );
    expect(state.queries[0].messageStatus).toBe('complete');
    expect(state.queries[0].response).toBe('Final answer.');
    expect(state.queries[0].error).toBeUndefined();
  });

  it('surfaces failed status as error and clears response', () => {
    const state = seedSlice();
    const next = reducer(
      state,
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'failed',
          response: 'whatever',
          error: 'worker died',
        },
      }),
    );
    expect(next.queries[0].messageStatus).toBe('failed');
    expect(next.queries[0].error).toBe('worker died');
    expect(next.queries[0].response).toBeUndefined();
  });
});

describe('raiseNotice — non-fatal notice', () => {
  it('records a notice without setting an error (turn is not failed)', () => {
    // seedSlice leaves conversationId at its initial null; match that.
    const state = seedSlice();
    const next = reducer(
      state,
      raiseNotice({
        conversationId: null,
        index: 0,
        message: 'big.txt was dropped (too large)',
      }),
    );
    expect(next.queries[0].notice).toBe('big.txt was dropped (too large)');
    expect(next.queries[0].error).toBeUndefined();
  });

  it('is a no-op when the conversationId does not match', () => {
    const state = seedSlice();
    const next = reducer(
      state,
      raiseNotice({
        conversationId: 'some-other-conversation',
        index: 0,
        message: 'ignored',
      }),
    );
    expect(next.queries[0].notice).toBeUndefined();
  });
});

const completedAtt = {
  id: 'srv-1',
  fileName: 'a.pdf',
  progress: 100,
  status: 'completed' as const,
  taskId: 't1',
};
const processingAtt = {
  id: 'c-2',
  fileName: 'b.pdf',
  progress: 40,
  status: 'processing' as const,
  taskId: 't2',
};

const preferenceStub = {
  token: 'tok',
  selectedDocs: [],
  prompt: { id: 'default' },
  chunks: '2',
  selectedAgent: null,
  selectedModel: null,
};

const makeStore = () =>
  configureStore({
    reducer: {
      conversation: reducer,
      upload: uploadReducer,
      preference: () => preferenceStub,
    },
  });

describe('fetchAnswer — attachment ids on the wire', () => {
  beforeEach(() => {
    vi.mocked(handleFetchAnswer)
      .mockClear()
      .mockResolvedValue(null as never);
  });

  it('sends explicit attachmentIds and leaves composer attachments untouched', async () => {
    const store = makeStore();
    store.dispatch(addQuery({ prompt: 'q' }));
    store.dispatch(addAttachment(completedAtt));

    await store.dispatch(
      fetchAnswer({
        question: 'q',
        indx: 0,
        attachmentIds: ['row-1', 'row-2'],
      }),
    );

    expect(vi.mocked(handleFetchAnswer).mock.calls[0][8]).toEqual([
      'row-1',
      'row-2',
    ]);
    // Explicit ids (e.g. a retry of an existing turn) must not consume
    // whatever the composer currently holds.
    expect(store.getState().upload.attachments).toHaveLength(1);
  });

  it('falls back to completed composer uploads and clears them when no ids are passed', async () => {
    const store = makeStore();
    store.dispatch(addQuery({ prompt: 'q' }));
    store.dispatch(addAttachment(completedAtt));
    store.dispatch(addAttachment(processingAtt));

    await store.dispatch(fetchAnswer({ question: 'q', indx: 0 }));

    expect(vi.mocked(handleFetchAnswer).mock.calls[0][8]).toEqual(['srv-1']);
    // clearAttachments keeps in-flight rows.
    expect(store.getState().upload.attachments.map((a) => a.id)).toEqual([
      'c-2',
    ]);
  });
  it('leaves a failed composer upload out of the fallback ids', async () => {
    const store = makeStore();
    store.dispatch(addQuery({ prompt: 'q' }));
    store.dispatch(addAttachment(completedAtt));
    store.dispatch(
      addAttachment({
        id: 'f-3',
        fileName: 'broken.pdf',
        progress: 0,
        status: 'failed',
        taskId: '',
      }),
    );

    await store.dispatch(fetchAnswer({ question: 'q', indx: 0 }));

    expect(vi.mocked(handleFetchAnswer).mock.calls[0][8]).toEqual(['srv-1']);
  });
});

describe('fetchAnswer.rejected', () => {
  it('writes the error to the retried row, not the last row', () => {
    let state = reducer(
      undefined,
      setConversation([{ prompt: 'first' }, { prompt: 'second' }]),
    );
    state = reducer(
      state,
      fetchAnswer.rejected(new Error('boom'), 'req-1', {
        question: 'first',
        indx: 0,
      }),
    );
    expect(state.status).toBe('failed');
    expect(state.queries[0].error).toBe('Something went wrong');
    expect(state.queries[1].error).toBeUndefined();
  });

  it('defaults to the last row when no index is given', () => {
    let state = reducer(
      undefined,
      setConversation([{ prompt: 'first' }, { prompt: 'second' }]),
    );
    state = reducer(
      state,
      fetchAnswer.rejected(new Error('boom'), 'req-1', { question: 'second' }),
    );
    expect(state.queries[0].error).toBeUndefined();
    expect(state.queries[1].error).toBe('Something went wrong');
  });
});

describe('resendQuery', () => {
  it('preserves the attachments bound to the turn', () => {
    let state = reducer(
      undefined,
      setConversation([
        {
          prompt: 'p',
          response: 'r',
          error: 'e',
          attachments: [{ id: 'x', fileName: 'f.pdf' }],
        },
      ]),
    );
    state = reducer(state, resendQuery({ index: 0, prompt: 'p2' }));
    expect(state.queries[0].attachments).toEqual([
      { id: 'x', fileName: 'f.pdf' },
    ]);
    expect(state.queries[0].response).toBeUndefined();
    expect(state.queries[0].error).toBeUndefined();
  });
});

describe('mapServerQueryToClient feedback', () => {
  // The API stores feedback lowercase (analytics counts 'like'/'dislike'),
  // while the thumbs compare against the FEEDBACK union.
  it.each([
    ['like', 'LIKE'],
    ['dislike', 'DISLIKE'],
    ['LIKE', 'LIKE'],
    ['Dislike', 'DISLIKE'],
  ])('maps stored %s to %s', (stored, expected) => {
    const query = mapServerQueryToClient({
      prompt: 'q',
      response: 'a',
      status: 'complete',
      feedback: stored,
    });
    expect(query.feedback).toBe(expected);
  });

  it('drops missing or unknown feedback', () => {
    for (const feedback of [undefined, null, '', 'meh']) {
      const query = mapServerQueryToClient({
        prompt: 'q',
        response: 'a',
        status: 'complete',
        feedback,
      });
      expect(query.feedback).toBeUndefined();
    }
  });
});

describe('curated errors', () => {
  it('keeps the code a failed row stored with its message', () => {
    const query = mapServerQueryToClient({
      prompt: 'q',
      status: 'failed',
      attachments: [{ id: 'a1', fileName: 'big.pdf' }],
      metadata: {
        error: 'This message and its attached files are too large.',
        error_code: 'context_length_exceeded',
      },
    });
    expect(query.error).toBe(
      'This message and its attached files are too large.',
    );
    expect(query.errorCode).toBe('context_length_exceeded');
  });

  it('reads an error stored as {message, code}', () => {
    const query = mapServerQueryToClient({
      prompt: 'q',
      status: 'failed',
      metadata: {
        error: { message: 'Too large.', code: 'context_length_exceeded' },
      },
    });
    expect(query.error).toBe('Too large.');
    expect(query.errorCode).toBe('context_length_exceeded');
  });

  it('leaves an older failed row without a code', () => {
    const query = mapServerQueryToClient({
      prompt: 'q',
      status: 'failed',
      metadata: { error: 'worker died' },
    });
    expect(query.error).toBe('worker died');
    expect(query.errorCode).toBeUndefined();
  });

  it('keeps the code from a failed tail', () => {
    const next = reducer(
      seedSlice(),
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'failed',
          error: 'Too large.',
          error_code: 'context_length_exceeded',
        },
      }),
    );
    expect(next.queries[0].error).toBe('Too large.');
    expect(next.queries[0].errorCode).toBe('context_length_exceeded');
  });

  it('records the code a live error event carries', () => {
    const next = reducer(
      seedSlice(),
      raiseError({
        conversationId: null,
        index: 0,
        message: 'Too large.',
        code: 'context_length_exceeded',
      }),
    );
    expect(next.queries[0].error).toBe('Too large.');
    expect(next.queries[0].errorCode).toBe('context_length_exceeded');
  });

  it('keeps the params an overflow was worded from', () => {
    const params = { needed_tokens: 300000, available_tokens: 200000 };
    const stored = mapServerQueryToClient({
      prompt: 'q',
      status: 'failed',
      metadata: {
        error: 'Too large.',
        error_code: 'context_length_exceeded',
        error_params: params,
      },
    });
    expect(stored.errorParams).toEqual(params);

    const tailed = reducer(
      seedSlice(),
      applyMessageTail({
        index: 0,
        tail: {
          message_id: 'm-1',
          status: 'failed',
          error: 'Too large.',
          error_code: 'context_length_exceeded',
          error_params: params,
        },
      }),
    );
    expect(tailed.queries[0].errorParams).toEqual(params);

    let live = reducer(
      seedSlice(),
      raiseError({
        conversationId: null,
        index: 0,
        message: 'Too large.',
        code: 'context_length_exceeded',
        params,
      }),
    );
    expect(live.queries[0].errorParams).toEqual(params);
    live = reducer(
      live,
      raiseError({ conversationId: null, index: 0, message: 'Oops' }),
    );
    expect(live.queries[0].errorParams).toBeUndefined();
  });

  it('drops a stale code when a later error has none', () => {
    let state = reducer(
      seedSlice(),
      raiseError({
        conversationId: null,
        index: 0,
        message: 'Too large.',
        code: 'context_length_exceeded',
      }),
    );
    state = reducer(
      state,
      raiseError({ conversationId: null, index: 0, message: 'Oops' }),
    );
    expect(state.queries[0].errorCode).toBeUndefined();
  });
});

describe('loadConversation with resolveAgent', () => {
  const agentA = { id: 'agent-a', name: 'A' } as Agent;
  const agentB = { id: 'agent-b', name: 'B' } as Agent;

  const makeLoadStore = () => {
    const store = configureStore({
      reducer: {
        conversation: reducer,
        upload: uploadReducer,
        preference: preferenceReducer,
      },
    });
    store.dispatch(setConversation([{ prompt: 'old chat' }]));
    store.dispatch(setSelectedAgent(agentA));
    return store;
  };

  const serveConversation = (agentId: string | null) =>
    vi.spyOn(conversationService, 'getConversation').mockResolvedValue({
      ok: true,
      json: async () => ({
        queries: [{ prompt: 'new chat', response: 'hi' }],
        agent_id: agentId,
      }),
    } as Response);

  const shown = (store: ReturnType<typeof makeLoadStore>) => ({
    prompt: store.getState().conversation.queries[0]?.prompt,
    agent: store.getState().preference.selectedAgent?.id ?? null,
  });

  it('resolves the agent before anything changes, then applies both', async () => {
    serveConversation('agent-b');
    const store = makeLoadStore();
    let duringResolve: ReturnType<typeof shown> | null = null;

    const result = await store
      .dispatch(
        loadConversation({
          id: 'c-2',
          force: true,
          resolveAgent: async () => {
            duringResolve = shown(store);
            return agentB;
          },
        }),
      )
      .unwrap();

    // The old chat keeps its agent card while the new one resolves.
    expect(duringResolve).toEqual({ prompt: 'old chat', agent: 'agent-a' });
    expect(shown(store)).toEqual({ prompt: 'new chat', agent: 'agent-b' });
    expect(store.getState().conversation.conversationId).toBe('c-2');
    expect(result.stale).toBe(false);
  });

  it('clears the agent for a chat without one', async () => {
    serveConversation(null);
    const store = makeLoadStore();

    await store.dispatch(
      loadConversation({
        id: 'c-2',
        force: true,
        resolveAgent: async () => null,
      }),
    );

    expect(shown(store)).toEqual({ prompt: 'new chat', agent: null });
  });

  it('leaves the agent alone without a resolver', async () => {
    serveConversation('agent-b');
    const store = makeLoadStore();

    await store.dispatch(loadConversation({ id: 'c-2', force: true }));

    expect(shown(store)).toEqual({ prompt: 'new chat', agent: 'agent-a' });
  });

  it('reports a superseded load as stale even when its resolver fails', async () => {
    serveConversation('agent-b');
    const store = makeLoadStore();
    let fail: ((error: Error) => void) | null = null;

    const first = store.dispatch(
      loadConversation({
        id: 'c-2',
        force: true,
        resolveAgent: () => new Promise<Agent>((_, reject) => (fail = reject)),
      }),
    );
    await vi.waitFor(() => expect(fail).not.toBeNull());
    await store.dispatch(
      loadConversation({
        id: 'c-3',
        force: true,
        resolveAgent: async () => null,
      }),
    );
    fail!(new TypeError('Failed to fetch'));

    // A rejection would send the caller to /c/new over the newer chat.
    await expect(first.unwrap()).resolves.toEqual({
      data: null,
      stale: true,
    });
    expect(store.getState().conversation.conversationId).toBe('c-3');
  });

  it('still fails the current load when its resolver fails', async () => {
    serveConversation('agent-b');
    const store = makeLoadStore();

    await expect(
      store
        .dispatch(
          loadConversation({
            id: 'c-2',
            force: true,
            resolveAgent: async () => {
              throw new TypeError('Failed to fetch');
            },
          }),
        )
        .unwrap(),
    ).rejects.toThrow('Failed to fetch');
    expect(shown(store)).toEqual({ prompt: 'old chat', agent: 'agent-a' });
  });

  it('applies nothing when a newer load superseded it', async () => {
    serveConversation('agent-b');
    const store = makeLoadStore();
    let release: ((agent: Agent) => void) | null = null;

    const first = store.dispatch(
      loadConversation({
        id: 'c-2',
        force: true,
        resolveAgent: () => new Promise<Agent>((r) => (release = r)),
      }),
    );
    await vi.waitFor(() => expect(release).not.toBeNull());
    await store.dispatch(
      loadConversation({
        id: 'c-3',
        force: true,
        resolveAgent: async () => null,
      }),
    );
    release!(agentB);
    const result = await first.unwrap();

    expect(result.stale).toBe(true);
    expect(store.getState().conversation.conversationId).toBe('c-3');
    expect(store.getState().preference.selectedAgent).toBeNull();
  });
});
