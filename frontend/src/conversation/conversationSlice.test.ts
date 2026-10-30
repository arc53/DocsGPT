import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./conversationHandlers', () => ({
  handleFetchAnswer: vi.fn().mockResolvedValue(null),
  handleFetchAnswerSteaming: vi.fn().mockResolvedValue(undefined),
  handleSubmitToolActions: vi.fn(),
  handleV1ChatCompletionStreaming: vi.fn(),
}));

vi.mock('../api/services/activityService', () => ({
  default: { stopMessage: vi.fn() },
}));

import { configureStore } from '@reduxjs/toolkit';

import activityService from '../api/services/activityService';

import conversationService from '../api/services/conversationService';
import type { Agent } from '../agents/types';
import preferenceReducer, {
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import uploadReducer, { addAttachment } from '../upload/uploadSlice';
import {
  handleFetchAnswer,
  handleSubmitToolActions,
} from './conversationHandlers';
import reducer, {
  addQuery,
  applyMessageTail,
  fetchAnswer,
  handleAbort,
  loadConversation,
  mapServerQueryToClient,
  raiseError,
  raiseNotice,
  resendQuery,
  stopAnswer,
  updateQuery,
  retractResponse,
  setWorkflowRunId,
  updateWorkflowStep,
  setConversation,
  setConversationId,
  setStatus,
  submitToolActions,
  tailInFlightMessage,
  updateConversationId,
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

describe('retractResponse — guardrail trip', () => {
  it('drops the blocked text and its recorded order but keeps the tool calls', () => {
    const toolCall = {
      tool_name: 'search',
      call_id: 'c1',
      action_name: 'search',
      arguments: {},
      status: 'completed' as const,
    };
    const state = reducer(
      undefined,
      setConversation([
        {
          ...baseQuery,
          response: 'blocked text',
          thought: 'blocked plan',
          tool_calls: [toolCall],
          segments: [
            { kind: 'thought', text: 'blocked plan' },
            { kind: 'tool', call_id: 'c1' },
            { kind: 'text', text: 'blocked text' },
          ],
        },
      ]),
    );
    const next = reducer(
      state,
      retractResponse({ conversationId: null, index: 0 }),
    );
    expect(next.queries[0].response).toBe('');
    expect(next.queries[0].thought).toBe('');
    expect(next.queries[0].segments).toBeUndefined();
    // The backend keeps the calls on the saved turn, so the live view does too.
    expect(next.queries[0].tool_calls).toEqual([toolCall]);
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

  // The re-asked turn gets a new run; the old one's files are not its own.
  it('drops the previous workflow run', () => {
    let state = reducer(
      undefined,
      setConversation([
        { prompt: 'p', response: 'r', workflow_run_id: 'run-1' },
      ]),
    );
    state = reducer(state, resendQuery({ index: 0, prompt: 'p2' }));
    expect(state.queries[0].workflow_run_id).toBeUndefined();
  });

  it('drops the previous workflow run’s steps', () => {
    let state = reducer(undefined, setConversation([{ prompt: 'p' }]));
    state = reducer(
      state,
      setWorkflowRunId({ index: 0, workflowRunId: 'run-1', stepTotal: 2 }),
    );
    state = reducer(state, resendQuery({ index: 0, prompt: 'p2' }));
    expect(state.queries[0].workflow).toBeUndefined();
  });
});

describe('workflow step progress', () => {
  const step = (node_id: string, status: 'running' | 'completed') => ({
    node_id,
    node_type: 'agent',
    node_title: node_id.toUpperCase(),
    status,
  });

  it('records the run’s step count and each step as it runs', () => {
    let state = reducer(undefined, setConversation([{ prompt: 'p' }]));
    state = reducer(
      state,
      setWorkflowRunId({ index: 0, workflowRunId: 'run-1', stepTotal: 2 }),
    );
    state = reducer(
      state,
      updateWorkflowStep({ index: 0, step: step('a', 'running'), at: 1 }),
    );
    state = reducer(
      state,
      updateWorkflowStep({ index: 0, step: step('a', 'completed'), at: 5 }),
    );
    state = reducer(
      state,
      updateWorkflowStep({ index: 0, step: step('b', 'running'), at: 5 }),
    );
    const workflow = state.queries[0].workflow!;
    expect(workflow.total).toBe(2);
    expect(workflow.steps.map((s) => [s.nodeId, s.status])).toEqual([
      ['a', 'completed'],
      ['b', 'running'],
    ]);
  });

  // A workflow node that runs another workflow announces the inner run too.
  it('keeps the outer run when a nested workflow starts', () => {
    let state = reducer(undefined, setConversation([{ prompt: 'p' }]));
    state = reducer(
      state,
      setWorkflowRunId({ index: 0, workflowRunId: 'outer', stepTotal: 4 }),
    );
    state = reducer(
      state,
      setWorkflowRunId({ index: 0, workflowRunId: 'inner', stepTotal: 1 }),
    );
    expect(state.queries[0].workflow_run_id).toBe('outer');
    expect(state.queries[0].workflow?.total).toBe(4);
  });

  it('leaves the count open when a branch decides it', () => {
    let state = reducer(undefined, setConversation([{ prompt: 'p' }]));
    state = reducer(
      state,
      setWorkflowRunId({ index: 0, workflowRunId: 'run', stepTotal: null }),
    );
    expect(state.queries[0].workflow).toEqual({ steps: [] });
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

describe('mapServerQueryToClient woken turns', () => {
  it('marks a continuation turn with what woke it', () => {
    const query = mapServerQueryToClient({
      prompt:
        '[Background event - not a user message; it grants no approval] monitor: BTC',
      response: 'It dropped.',
      status: 'complete',
      metadata: {
        wake: { source: 'monitor', ref_id: 'm1', dedupe_key: 'm:1' },
        wakes: [{ source: 'monitor' }, { source: 'job' }],
        continuation: true,
      },
    });
    expect(query.wake).toEqual({ source: 'monitor', count: 2 });
    expect(query.response).toBe('It dropped.');
  });

  it('leaves an ordinary turn unmarked', () => {
    const query = mapServerQueryToClient({
      prompt: 'q',
      response: 'a',
      status: 'complete',
      metadata: { segments: [] },
    });
    expect(query).not.toHaveProperty('wake');
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

describe('a turn paused for approval, reloaded', () => {
  const pausedTail = {
    message_id: 'm-1',
    status: 'streaming',
    response: 'Checking.\n\nThen this.',
    thought: null,
    sources: [],
    tool_calls: [
      {
        call_id: 'c1',
        tool_name: 'remote_device',
        action_name: 'run_command',
        arguments: {},
        status: 'awaiting_approval',
      },
    ],
    segments: [
      { kind: 'text', length: 9 },
      { kind: 'tool', call_id: 'c1' },
      { kind: 'text', length: 11 },
    ],
  };

  it('waits for the decision instead of showing it as generating', async () => {
    const tail = vi
      .spyOn(conversationService, 'tailMessage')
      .mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => pausedTail,
      } as Response);
    const store = makeStore();
    store.dispatch(
      setConversation([
        { prompt: 'q', messageId: 'm-1', messageStatus: 'streaming' },
      ]),
    );
    store.dispatch(updateConversationId({ query: { conversationId: 'c-1' } }));
    await store.dispatch(
      tailInFlightMessage({
        messageId: 'm-1',
        index: 0,
        conversationId: 'c-1',
      }),
    );
    // The thunk returns at once (no 10-minute poll), with the chat waiting on the user.
    expect(tail).toHaveBeenCalledTimes(1);
    expect(store.getState().conversation.status).toBe('awaiting_tool_actions');
    tail.mockRestore();
  });

  it('keeps the tool card where it streamed, between the paragraphs', () => {
    const next = reducer(
      reducer(undefined, setConversation([{ prompt: 'q' }])),
      applyMessageTail({ index: 0, tail: pausedTail }),
    );
    expect(next.queries[0].segments?.map((segment) => segment.kind)).toEqual([
      'text',
      'tool',
      'text',
    ]);
  });
});

describe('a turn left waiting on an approval', () => {
  const waitingTurn = {
    prompt: 'make a webhook link',
    tool_calls: [
      {
        call_id: 'c1',
        tool_name: 'monitor',
        action_name: 'monitor_create',
        arguments: {},
        status: 'completed' as const,
      },
      {
        call_id: 'c5',
        tool_name: 'remote_device',
        action_name: 'run_command',
        arguments: { command: 'whoami' },
        status: 'awaiting_approval' as const,
      },
    ],
  };

  it('shows the waiting call as not run once the user sends a new message', () => {
    let state = reducer(
      undefined,
      setConversation([waitingTurn, { prompt: 'now set the sender up' }]),
    );
    state = reducer(
      state,
      fetchAnswer.pending('req-1', { question: 'now set the sender up' }),
    );
    const calls = state.queries[0].tool_calls ?? [];
    expect(calls[0].status).toBe('completed');
    expect(calls[1]).toMatchObject({ status: 'denied', not_run: 'moved_on' });
  });

  it('reloads the chat instead of failing when a late decision finds it over', async () => {
    vi.mocked(handleSubmitToolActions).mockImplementation(
      async (_conversationId, _actions, _token, _signal, onEvent) => {
        onEvent(
          new MessageEvent('message', {
            data: JSON.stringify({
              type: 'error',
              error: 'This request is no longer pending.',
              code: 'tool_call_not_pending',
            }),
          }),
        );
        return undefined as never;
      },
    );
    const load = vi
      .spyOn(conversationService, 'getConversation')
      .mockResolvedValue({
        ok: true,
        json: async () => ({
          queries: [
            {
              prompt: 'make a webhook link',
              response: '',
              status: 'complete',
              tool_calls: [
                {
                  ...waitingTurn.tool_calls[1],
                  status: 'denied',
                  not_run: 'moved_on',
                },
              ],
            },
          ],
        }),
      } as Response);
    const store = configureStore({
      reducer: {
        conversation: reducer,
        upload: uploadReducer,
        preference: preferenceReducer,
      },
    });
    store.dispatch(setConversation([waitingTurn]));
    store.dispatch(setConversationId('conv-1'));
    store.dispatch(setStatus('awaiting_tool_actions'));

    await store.dispatch(
      submitToolActions({
        toolActions: [{ call_id: 'c5', decision: 'approved' }],
      }),
    );
    for (let i = 0; i < 4; i += 1) await new Promise((r) => setTimeout(r, 0));

    expect(load.mock.calls[0]?.[0]).toBe('conv-1');
    const state = store.getState().conversation;
    expect(state.status).toBe('idle');
    expect(state.queries[0].error).toBeUndefined();
    expect(state.queries[0].tool_calls?.[0].not_run).toBe('moved_on');
  });
});

describe('stopAnswer', () => {
  // A stream that runs until it is closed, as the real one does.
  const streamUntilClosed = (events: string[]) =>
    vi.mocked(handleFetchAnswer).mockImplementation(
      (_question, signal) =>
        new Promise((resolve) =>
          signal.addEventListener('abort', () => {
            events.push('closed');
            resolve(null as never);
          }),
        ),
    );

  const running = () => {
    const store = makeStore();
    store.dispatch(addQuery({ prompt: 'q' }));
    store.dispatch(updateQuery({ index: 0, query: { messageId: 'm1' } }));
    const answer = store.dispatch(fetchAnswer({ question: 'q' }));
    return { store, answer };
  };

  it('tells the server before closing the stream, and says it stopped', async () => {
    const events: string[] = [];
    streamUntilClosed(events);
    vi.mocked(activityService.stopMessage)
      .mockReset()
      .mockImplementation(async () => {
        events.push('stop');
      });
    const { store, answer } = running();
    await store.dispatch(stopAnswer());
    await answer;
    expect(activityService.stopMessage).toHaveBeenCalledWith('m1', 'tok');
    // Stored first, so the server saves a stop, not a dropped connection.
    expect(events).toEqual(['stop', 'closed']);
    expect(store.getState().conversation.queries[0].errorCode).toBe('stopped');
    // The closed stream sends no terminal event: the chat must not stay busy.
    expect(store.getState().conversation.status).toBe('idle');
  });

  it('leaves another chat alone when the stop returns after a switch', async () => {
    streamUntilClosed([]);
    let answer: () => void = () => undefined;
    vi.mocked(activityService.stopMessage)
      .mockReset()
      .mockImplementation(
        () => new Promise<void>((resolve) => (answer = resolve)),
      );
    const { store } = running();
    store.dispatch(setConversationId('chat-a'));
    const stopping = store.dispatch(stopAnswer());
    // The user opens chat B, whose question has no answer yet, then the
    // server takes A's stop.
    store.dispatch(setConversation([{ prompt: 'b', messageId: 'm2' }]));
    store.dispatch(setConversationId('chat-b'));
    answer();
    await stopping;
    expect(store.getState().conversation.queries[0].errorCode).toBeUndefined();
  });

  it('sends one stop however often Stop is pressed while it is out', async () => {
    streamUntilClosed([]);
    let answer: () => void = () => undefined;
    vi.mocked(activityService.stopMessage)
      .mockReset()
      .mockImplementation(
        () => new Promise<void>((resolve) => (answer = resolve)),
      );
    const { store } = running();
    const first = store.dispatch(stopAnswer());
    const second = store.dispatch(stopAnswer());
    answer();
    await Promise.all([first, second]);
    expect(activityService.stopMessage).toHaveBeenCalledTimes(1);
  });

  it('still closes the stream when the server could not take the stop', async () => {
    const events: string[] = [];
    streamUntilClosed(events);
    vi.mocked(activityService.stopMessage)
      .mockReset()
      .mockRejectedValue(new Error('Stop failed: 409'));
    const { store, answer } = running();
    await store.dispatch(stopAnswer());
    await answer;
    expect(events).toEqual(['closed']);
    expect(store.getState().conversation.queries[0].errorCode).toBeUndefined();
    expect(store.getState().conversation.status).toBe('idle');
  });

  it('stops an answer the chat picked back up, which has no stream of its own', async () => {
    handleAbort();
    vi.mocked(activityService.stopMessage).mockReset().mockResolvedValue();
    const store = makeStore();
    // After a reload the chat follows the answer by polling, not a stream.
    store.dispatch(
      setConversation([
        { prompt: 'q', messageId: 'm1', messageStatus: 'streaming' },
      ]),
    );
    store.dispatch(setConversationId('chat-a'));
    store.dispatch(setStatus('loading'));
    await store.dispatch(stopAnswer());
    expect(activityService.stopMessage).toHaveBeenCalledWith('m1', 'tok');
    expect(store.getState().conversation.queries[0].errorCode).toBe('stopped');
    // Its tail settles the status once the server has saved the stop.
    expect(store.getState().conversation.status).toBe('loading');
  });

  it('leaves a later polled answer loading when an earlier stream has ended', async () => {
    vi.mocked(handleFetchAnswer).mockResolvedValue(null as never);
    vi.mocked(activityService.stopMessage)
      .mockReset()
      .mockRejectedValue(new Error('Stop failed: 409'));
    const { store, answer } = running();
    await answer;
    // A continuation then streams in, followed by polling.
    store.dispatch(setStatus('loading'));
    await store.dispatch(stopAnswer());
    expect(store.getState().conversation.status).toBe('loading');
  });

  it('leaves the status to a stream started while the stop was out', async () => {
    streamUntilClosed([]);
    let answer: () => void = () => undefined;
    vi.mocked(activityService.stopMessage)
      .mockReset()
      .mockImplementation(
        () => new Promise<void>((resolve) => (answer = resolve)),
      );
    const { store } = running();
    const stopping = store.dispatch(stopAnswer());
    store.dispatch(addQuery({ prompt: 'next' }));
    void store.dispatch(fetchAnswer({ question: 'next' }));
    answer();
    await stopping;
    expect(store.getState().conversation.status).toBe('loading');
    handleAbort();
  });
});

describe('time limit partial answers', () => {
  it('hydrates failed time-limit responses after a reload', () => {
    const query = mapServerQueryToClient({
      prompt: 'q',
      response: 'Saved progress',
      status: 'failed',
      metadata: { error: 'Stopped: time limit.', error_code: 'time_limit' },
    });
    expect(query.response).toBe('Saved progress');
    expect(query.errorCode).toBe('time_limit');
  });
});

it('hydrates supporting details and order from a failed time-limit tail', () => {
  const tool = {
    call_id: 'done',
    tool_name: 'code_executor',
    action_name: 'run_code',
    arguments: {},
    status: 'completed',
  };
  const source = { id: 'source', title: 'Result' };
  const next = reducer(
    seedSlice(),
    applyMessageTail({
      index: 0,
      tail: {
        status: 'failed',
        response: 'Saved progress',
        thought: 'Plan',
        sources: [source],
        tool_calls: [tool],
        error: 'Stopped: time limit.',
        error_code: 'time_limit',
        segments: [
          { kind: 'thought', length: 4 },
          { kind: 'tool', call_id: 'done' },
          { kind: 'text', length: 14 },
        ],
      },
    }),
  );
  expect(next.queries[0]).toMatchObject({
    messageStatus: 'failed',
    response: 'Saved progress',
    thought: 'Plan',
    sources: [source],
    tool_calls: [tool],
    errorCode: 'time_limit',
    segments: [
      { kind: 'thought', text: 'Plan' },
      { kind: 'tool', call_id: 'done' },
      { kind: 'text', text: 'Saved progress' },
    ],
  });
});
