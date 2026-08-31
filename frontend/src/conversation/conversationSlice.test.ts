import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./conversationHandlers', () => ({
  handleFetchAnswer: vi.fn().mockResolvedValue(null),
  handleFetchAnswerSteaming: vi.fn().mockResolvedValue(undefined),
  handleSubmitToolActions: vi.fn(),
  handleV1ChatCompletionStreaming: vi.fn(),
}));

import { configureStore } from '@reduxjs/toolkit';

import uploadReducer, { addAttachment } from '../upload/uploadSlice';
import { handleFetchAnswer } from './conversationHandlers';
import reducer, {
  addQuery,
  applyMessageTail,
  fetchAnswer,
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
