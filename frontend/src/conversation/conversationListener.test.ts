import { configureStore } from '@reduxjs/toolkit';
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from 'vitest';

import conversationService from '../api/services/conversationService';
import {
  sseEventReceived,
  type SSEEvent,
} from '../notifications/notificationsSlice';
import * as preferenceApi from '../preferences/preferenceApi';
import { type Preference, prefSlice } from '../preferences/preferenceSlice';
import { type ConversationState } from './conversationModels';
import { handleFetchAnswer } from './conversationHandlers';
import {
  conversationListenerMiddleware,
  conversationSlice,
  fetchAnswer,
  setConversation,
  tailInFlightMessage,
} from './conversationSlice';

vi.mock('./conversationHandlers', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./conversationHandlers')>()),
  handleFetchAnswer: vi.fn(),
}));

vi.mock('../api/services/conversationService', () => ({
  default: {
    getConversation: vi.fn(),
    tailMessage: vi.fn(),
    getConversations: vi.fn(),
    answer: vi.fn(),
    answerStream: vi.fn(),
    search: vi.fn(),
    feedback: vi.fn(),
    shareConversation: vi.fn(),
  },
}));

const attention = vi.hoisted(() => ({ attended: true }));
vi.mock('../backgroundJobs/usePageVisible', () => ({
  isPageAttended: () => attention.attended,
}));

vi.mock('../preferences/preferenceApi', async () => {
  const actual = await vi.importActual<typeof preferenceApi>(
    '../preferences/preferenceApi',
  );
  return { ...actual, getConversations: vi.fn() };
});

const ENVELOPE = (overrides: Partial<SSEEvent> = {}): SSEEvent => ({
  id: 'evt-msg-1',
  ts: '2026-05-19T12:34:56Z',
  type: 'schedule.message.appended',
  payload: {
    conversation_id: 'conv-1',
    message_id: 'msg-1',
    schedule_id: 'sched-1',
    run_id: 'run-1',
  },
  ...overrides,
});

const makeStore = (
  initialConversationId: string | null = null,
  initialStatus: ConversationState['status'] = 'idle',
) => {
  const preference: Preference = {
    apiKey: '',
    prompt: { name: 'default', id: 'default', type: 'public' },
    prompts: [],
    chunks: '2',
    selectedDocs: [],
    sourceDocs: null,
    conversations: { data: null, loading: false },
    token: 'tok-1',
    modalState: 'INACTIVE',
    paginatedDocuments: null,
    templateAgents: null,
    agents: null,
    sharedAgents: null,
    selectedAgent: null,
    selectedModel: null,
    availableModels: [],
    modelsLoading: false,
    agentFolders: null,
    roles: [],
    rolesResolved: false,
    ttsAvailable: true,
    sttAvailable: true,
    authRequired: false,
    attachmentBudgetShare: null,
    analyticsEnabled: false,
    analyticsMaxTopics: 15,
    analyticsMaxOverlapping: 20,
  };
  const conversation: ConversationState = {
    queries: [],
    status: initialStatus,
    conversationId: initialConversationId,
  };
  return configureStore({
    reducer: {
      preference: prefSlice.reducer,
      conversation: conversationSlice.reducer,
    },
    preloadedState: { preference, conversation },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware().concat(conversationListenerMiddleware.middleware),
  });
};

describe('conversation listener — schedule.message.appended', () => {
  beforeEach(() => {
    (conversationService.getConversation as unknown as Mock).mockReset();
    (preferenceApi.getConversations as unknown as Mock).mockReset();
    (conversationService.getConversation as unknown as Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        queries: [
          { prompt: 'hi', response: 'hello', status: 'complete' },
          {
            prompt: '',
            response: 'scheduled run output',
            status: 'complete',
          },
        ],
      }),
    });
    (preferenceApi.getConversations as unknown as Mock).mockResolvedValue({
      data: [{ id: 'conv-1', name: 'Scheduled chat', agent_id: 'agent-1' }],
      loading: false,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('refetches the open conversation when the appended message lands on it', async () => {
    const store = makeStore('conv-1');
    store.dispatch(sseEventReceived(ENVELOPE()));
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    expect(conversationService.getConversation).toHaveBeenCalledWith(
      'conv-1',
      'tok-1',
    );
    const state = store.getState();
    expect(state.conversation.queries).toHaveLength(2);
    expect(state.conversation.queries[1].response).toBe('scheduled run output');
    expect(state.conversation.conversationId).toBe('conv-1');
  });

  it('refreshes the conversations sidebar list so the bumped chat reorders', async () => {
    const store = makeStore('conv-other');
    store.dispatch(sseEventReceived(ENVELOPE()));
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    expect(preferenceApi.getConversations).toHaveBeenCalledWith('tok-1');
    const list = store.getState().preference.conversations;
    expect(list.data).toEqual([
      { id: 'conv-1', name: 'Scheduled chat', agent_id: 'agent-1' },
    ]);
  });

  it('does not refetch the open conversation when the appended message targets a different chat', async () => {
    const store = makeStore('conv-other');
    store.dispatch(sseEventReceived(ENVELOPE()));
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    expect(conversationService.getConversation).not.toHaveBeenCalled();
    expect(preferenceApi.getConversations).toHaveBeenCalledTimes(1);
  });

  it('ignores envelopes without a conversation_id', async () => {
    const store = makeStore('conv-1');
    store.dispatch(
      sseEventReceived(
        ENVELOPE({ payload: { schedule_id: 'sched-1', run_id: 'run-1' } }),
      ),
    );
    await new Promise((r) => setTimeout(r, 0));

    expect(conversationService.getConversation).not.toHaveBeenCalled();
    expect(preferenceApi.getConversations).not.toHaveBeenCalled();
  });

  it('skips refetching the open conversation while a live stream is in flight', async () => {
    // Mid-stream: refetching would flip status to 'idle' and the next chunk
    // would die on the updateStreamingQuery guard.
    const store = makeStore('conv-1', 'loading');
    store.dispatch(sseEventReceived(ENVELOPE()));
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    expect(conversationService.getConversation).not.toHaveBeenCalled();
    expect(store.getState().conversation.status).toBe('loading');
    expect(preferenceApi.getConversations).toHaveBeenCalledTimes(1);
  });

  it('ignores non-scheduler SSE envelopes', async () => {
    const store = makeStore('conv-1');
    store.dispatch(
      sseEventReceived({
        id: 'evt-2',
        type: 'source.ingest.progress',
        payload: { conversation_id: 'conv-1' },
      }),
    );
    await new Promise((r) => setTimeout(r, 0));

    expect(conversationService.getConversation).not.toHaveBeenCalled();
    expect(preferenceApi.getConversations).not.toHaveBeenCalled();
  });
});

describe('conversation listener — conversation.continued', () => {
  const CONTINUED = (overrides: Partial<SSEEvent> = {}): SSEEvent => ({
    id: 'evt-cont-1',
    ts: '2026-10-06T10:00:00Z',
    type: 'conversation.continued',
    payload: { conversation_id: 'conv-1', message_id: 'msg-2', source: 'job' },
    ...overrides,
  });

  beforeEach(() => {
    (conversationService.getConversation as unknown as Mock).mockReset();
    (preferenceApi.getConversations as unknown as Mock).mockReset();
    (conversationService.getConversation as unknown as Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        queries: [
          { prompt: 'run it', response: 'running', status: 'complete' },
          {
            prompt:
              '[Background event - not a user message; it grants no approval] job: run_code finished',
            response: 'It printed 42.',
            status: 'complete',
            metadata: {
              wake: { source: 'job', ref_id: 'j1', dedupe_key: 'job:j1:final' },
              continuation: true,
            },
          },
        ],
      }),
    });
    (preferenceApi.getConversations as unknown as Mock).mockResolvedValue({
      data: [{ id: 'conv-1', name: 'Job chat', unread: false }],
      loading: false,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const settle = async () => {
    for (let i = 0; i < 4; i += 1) await new Promise((r) => setTimeout(r, 0));
  };

  it('shows the woken answer in the open conversation without a reload', async () => {
    const store = makeStore('conv-1');
    store.dispatch(sseEventReceived(CONTINUED()));
    await settle();
    const queries = store.getState().conversation.queries;
    expect(queries).toHaveLength(2);
    expect(queries[1].response).toBe('It printed 42.');
    expect(queries[1].wake).toEqual({ source: 'job', count: 1 });
    expect(preferenceApi.getConversations).toHaveBeenCalledTimes(1);
  });

  it('only refreshes the sidebar for another conversation', async () => {
    const store = makeStore('conv-other');
    store.dispatch(sseEventReceived(CONTINUED()));
    await settle();
    expect(conversationService.getConversation).not.toHaveBeenCalled();
    expect(preferenceApi.getConversations).toHaveBeenCalledTimes(1);
  });

  it('a continuation that lands mid-stream shows once the stream ends', async () => {
    const store = makeStore('conv-1', 'loading');
    store.dispatch(sseEventReceived(CONTINUED()));
    await settle();
    expect(conversationService.getConversation).not.toHaveBeenCalled();

    store.dispatch(conversationSlice.actions.setStatus('idle'));
    await settle();
    expect(conversationService.getConversation).toHaveBeenCalledWith(
      'conv-1',
      'tok-1',
    );
  });

  it('not if the user left that conversation meanwhile', async () => {
    const store = makeStore('conv-1', 'loading');
    store.dispatch(sseEventReceived(CONTINUED()));
    await settle();
    store.dispatch(conversationSlice.actions.setConversationId('conv-2'));
    store.dispatch(conversationSlice.actions.setStatus('idle'));
    await settle();
    expect(conversationService.getConversation).not.toHaveBeenCalled();
  });
});

describe('conversation listener — a continuation starts in the open chat', () => {
  const STARTED = (overrides: Partial<SSEEvent> = {}): SSEEvent => ({
    id: 'evt-start-1',
    ts: '2026-10-20T10:52:40Z',
    type: 'message.started',
    payload: { conversation_id: 'conv-1', message_id: 'msg-2' },
    ...overrides,
  });

  const LOADED = {
    queries: [
      {
        prompt: 'make the file',
        response: 'working on it',
        status: 'complete',
        message_id: 'msg-1',
      },
      {
        prompt: '[Background event - not a user message] job finished',
        response:
          'Response was terminated prior to completion, try regenerating.',
        status: 'streaming',
        message_id: 'msg-2',
        metadata: {
          wake: { source: 'job', ref_id: 'j1', dedupe_key: 'job:j1:final' },
          continuation: true,
        },
      },
    ],
  };

  const settle = async () => {
    for (let i = 0; i < 6; i += 1) await new Promise((r) => setTimeout(r, 0));
  };

  beforeEach(() => {
    (conversationService.getConversation as unknown as Mock).mockReset();
    (conversationService.tailMessage as unknown as Mock).mockReset();
    (preferenceApi.getConversations as unknown as Mock).mockReset();
    (conversationService.getConversation as unknown as Mock).mockResolvedValue({
      ok: true,
      json: async () => LOADED,
    });
    (conversationService.tailMessage as unknown as Mock).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        message_id: 'msg-2',
        status: 'complete',
        response: 'Your file is ready.',
      }),
    });
    (preferenceApi.getConversations as unknown as Mock).mockResolvedValue({
      data: [{ id: 'conv-1', name: 'Job chat' }],
      loading: false,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads the chat and follows the answer as it is written', async () => {
    const store = makeStore('conv-1');
    store.dispatch(
      setConversation([
        {
          prompt: 'make the file',
          response: 'working on it',
          messageId: 'msg-1',
        },
      ]),
    );
    store.dispatch(sseEventReceived(STARTED()));
    await settle();
    expect(conversationService.getConversation).toHaveBeenCalledWith(
      'conv-1',
      'tok-1',
    );
    expect(conversationService.tailMessage).toHaveBeenCalledWith(
      'msg-2',
      'tok-1',
    );
    const queries = store.getState().conversation.queries;
    expect(queries[1].response).toBe('Your file is ready.');
  });

  it('leaves an answer this tab is streaming to its own stream', async () => {
    const store = makeStore('conv-1', 'loading');
    store.dispatch(sseEventReceived(STARTED()));
    await settle();
    expect(conversationService.getConversation).not.toHaveBeenCalled();
  });

  it('drops the reload when the user starts an answer while it loads', async () => {
    let release: (value: unknown) => void = () => {};
    (conversationService.getConversation as unknown as Mock).mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    const store = makeStore('conv-1');
    store.dispatch(
      setConversation([{ prompt: 'new question', messageId: 'msg-local' }]),
    );
    store.dispatch(sseEventReceived(STARTED()));
    await settle();
    store.dispatch(conversationSlice.actions.setStatus('loading'));
    release({ ok: true, json: async () => LOADED });
    await settle();
    const state = store.getState().conversation;
    expect(state.status).toBe('loading');
    expect(state.queries).toHaveLength(1);
    expect(state.queries[0].prompt).toBe('new question');
  });

  it('leaves a newer answer alone when an old tail finds its message gone', async () => {
    (conversationService.tailMessage as unknown as Mock).mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ status: 'not found' }),
    });
    const store = makeStore('conv-1');
    store.dispatch(
      setConversation([
        { prompt: 'woken', messageId: 'msg-2', messageStatus: 'streaming' },
        { prompt: 'new question', messageId: 'msg-3' },
      ]),
    );
    await store.dispatch(
      tailInFlightMessage({
        messageId: 'msg-2',
        index: 0,
        conversationId: 'conv-1',
      }),
    );
    expect(store.getState().conversation.status).toBe('loading');
    expect(conversationService.getConversation).not.toHaveBeenCalled();
  });

  it('leaves an answer the chat already shows alone', async () => {
    const store = makeStore('conv-1');
    store.dispatch(
      setConversation([{ prompt: 'q', response: 'a', messageId: 'msg-2' }]),
    );
    store.dispatch(sseEventReceived(STARTED()));
    await settle();
    expect(conversationService.getConversation).not.toHaveBeenCalled();
  });

  it('does not load a chat it is not showing', async () => {
    const store = makeStore('conv-other');
    store.dispatch(sseEventReceived(STARTED()));
    await settle();
    expect(conversationService.getConversation).not.toHaveBeenCalled();
  });

  it('reloads the chat when the answer it follows is taken back out', async () => {
    // A continuation that ended silent (NO_REPLY) or failed deletes its row.
    (conversationService.tailMessage as unknown as Mock).mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ status: 'not found' }),
    });
    const store = makeStore('conv-1');
    store.dispatch(sseEventReceived(STARTED()));
    await settle();
    expect(
      (conversationService.getConversation as unknown as Mock).mock.calls
        .length,
    ).toBeGreaterThanOrEqual(2);
    expect(store.getState().conversation.status).not.toBe('loading');
  });
});

describe('conversation listener — tool.approval.cleared', () => {
  // Another tab moved past (or outwaited) the approval this tab still shows:
  // reload the open chat so the card becomes the call that never ran.
  const CLEARED = (reason: string, conversationId = 'conv-1'): SSEEvent => ({
    id: 'evt-clear-1',
    ts: '2026-10-06T10:00:00Z',
    type: 'tool.approval.cleared',
    payload: {
      conversation_id: conversationId,
      message_id: 'msg-1',
      reason,
    },
    scope: { kind: 'conversation', id: conversationId },
  });

  const settle = async () => {
    for (let i = 0; i < 4; i += 1) await new Promise((r) => setTimeout(r, 0));
  };

  beforeEach(() => {
    (conversationService.getConversation as unknown as Mock).mockReset();
    (preferenceApi.getConversations as unknown as Mock).mockReset();
    (conversationService.getConversation as unknown as Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        queries: [
          {
            prompt: 'make a webhook',
            response: 'Set it up.',
            status: 'complete',
            tool_calls: [
              {
                call_id: 'c5',
                tool_name: 'remote_device',
                action_name: 'run_command',
                arguments: {},
                status: 'denied',
                not_run: 'moved_on',
              },
            ],
          },
          { prompt: 'now the sender', response: 'Done.', status: 'complete' },
        ],
      }),
    });
  });

  it.each(['moved_on', 'expired'])(
    'reloads the open chat waiting on that approval (%s)',
    async (reason) => {
      const store = makeStore('conv-1', 'awaiting_tool_actions');
      store.dispatch(sseEventReceived(CLEARED(reason)));
      await settle();
      expect(conversationService.getConversation).toHaveBeenCalledWith(
        'conv-1',
        'tok-1',
      );
      const queries = store.getState().conversation.queries;
      expect(queries[0].tool_calls?.[0].status).toBe('denied');
      expect(store.getState().conversation.status).toBe('idle');
    },
  );

  it('leaves a decided approval to the stream that resumed it', async () => {
    const store = makeStore('conv-1', 'awaiting_tool_actions');
    store.dispatch(sseEventReceived(CLEARED('decided')));
    await settle();
    expect(conversationService.getConversation).not.toHaveBeenCalled();
  });

  it('never interrupts a stream, and reloads once it ends', async () => {
    const store = makeStore('conv-1', 'loading');
    store.dispatch(sseEventReceived(CLEARED('moved_on')));
    await settle();
    expect(conversationService.getConversation).not.toHaveBeenCalled();
    expect(store.getState().conversation.status).toBe('loading');

    store.dispatch(conversationSlice.actions.setStatus('idle'));
    await settle();
    expect(conversationService.getConversation).toHaveBeenCalledWith(
      'conv-1',
      'tok-1',
    );
  });

  it('not after a stream if the user left that conversation meanwhile', async () => {
    const store = makeStore('conv-1', 'loading');
    store.dispatch(sseEventReceived(CLEARED('expired')));
    await settle();
    store.dispatch(conversationSlice.actions.setConversationId('conv-2'));
    store.dispatch(conversationSlice.actions.setStatus('idle'));
    await settle();
    expect(conversationService.getConversation).not.toHaveBeenCalled();
  });

  it('ignores another conversation', async () => {
    const store = makeStore('conv-2', 'idle');
    store.dispatch(sseEventReceived(CLEARED('moved_on')));
    await settle();
    expect(conversationService.getConversation).not.toHaveBeenCalled();
  });
});

describe('listener middleware export hygiene', () => {
  it('exports the listener middleware so the store can wire it', () => {
    expect(conversationListenerMiddleware).toBeDefined();
    expect(typeof conversationListenerMiddleware.middleware).toBe('function');
  });

  it('still exports the slice actions consumers rely on', () => {
    expect(typeof setConversation).toBe('function');
  });
});

describe('conversation listener — a new chat in the sidebar', () => {
  const flush = async () => {
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
  };
  const started = (conversationId: string, id = `evt-${conversationId}`) =>
    ENVELOPE({
      id,
      type: 'message.started',
      payload: { conversation_id: conversationId, message_id: 'm-1' },
    });
  const listed = (ids: string[]) =>
    prefSlice.actions.receiveConversations({
      data: ids.map((id) => ({ id, name: id })) as never,
      loading: false,
    });

  beforeEach(() => {
    (preferenceApi.getConversations as unknown as Mock).mockReset();
    (preferenceApi.getConversations as unknown as Mock).mockResolvedValue({
      data: [{ id: 'conv-new', name: 'What is the weather' }],
      loading: false,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('lists a chat this tab just started, as soon as the stream names it', async () => {
    const store = makeStore(null, 'loading');
    store.dispatch(conversationSlice.actions.setConversationId('conv-new'));
    await flush();
    expect(preferenceApi.getConversations).toHaveBeenCalledTimes(1);
    expect(
      store.getState().preference.conversations.data?.map((c) => c.id),
    ).toEqual(['conv-new']);
  });

  it('lists a chat started in another tab when its answer starts', async () => {
    const store = makeStore();
    store.dispatch(sseEventReceived(started('conv-new')));
    await flush();
    expect(preferenceApi.getConversations).toHaveBeenCalledTimes(1);
  });

  it('fetches once when the stream and the event both announce it', async () => {
    const store = makeStore(null, 'loading');
    store.dispatch(conversationSlice.actions.setConversationId('conv-new'));
    store.dispatch(sseEventReceived(started('conv-new')));
    await flush();
    expect(preferenceApi.getConversations).toHaveBeenCalledTimes(1);
  });

  it('leaves a chat the sidebar already lists alone', async () => {
    const store = makeStore();
    store.dispatch(listed(['conv-old']));
    store.dispatch(sseEventReceived(started('conv-old')));
    await flush();
    expect(preferenceApi.getConversations).not.toHaveBeenCalled();
  });

  it('refreshes the list when a chat it is not showing finishes, for its unread mark', async () => {
    const store = makeStore('conv-open');
    store.dispatch(listed(['conv-old', 'conv-open']));
    store.dispatch(
      sseEventReceived(
        ENVELOPE({
          id: 'evt-finished',
          type: 'message.finished',
          payload: { conversation_id: 'conv-old', message_id: 'm-1' },
        }),
      ),
    );
    await flush();
    expect(preferenceApi.getConversations).toHaveBeenCalledTimes(1);
  });

  it('leaves the chat it shows to its own stream end', async () => {
    attention.attended = true;
    window.history.pushState({}, '', '/c/conv-open');
    const store = makeStore('conv-open');
    store.dispatch(listed(['conv-open']));
    store.dispatch(
      sseEventReceived(
        ENVELOPE({
          id: 'evt-finished-open',
          type: 'message.finished',
          payload: { conversation_id: 'conv-open', message_id: 'm-1' },
        }),
      ),
    );
    await flush();
    window.history.pushState({}, '', '/');
    expect(preferenceApi.getConversations).not.toHaveBeenCalled();
  });

  it('leaves a new chat it is streaming to its own stream end', async () => {
    attention.attended = true;
    window.history.pushState({}, '', '/c/new');
    const store = makeStore('conv-new', 'loading');
    store.dispatch(listed(['conv-new']));
    store.dispatch(
      sseEventReceived(
        ENVELOPE({
          id: 'evt-finished-new',
          type: 'message.finished',
          payload: { conversation_id: 'conv-new', message_id: 'm-1' },
        }),
      ),
    );
    await flush();
    window.history.pushState({}, '', '/');
    expect(preferenceApi.getConversations).not.toHaveBeenCalled();
  });

  it('refreshes the last chat it showed once the user moved to another page', async () => {
    // The chat stays in state on /settings, but nobody is looking at it: the
    // server marked it unread.
    attention.attended = true;
    window.history.pushState({}, '', '/settings');
    const store = makeStore('conv-open');
    store.dispatch(listed(['conv-open']));
    store.dispatch(
      sseEventReceived(
        ENVELOPE({
          id: 'evt-finished-settings',
          type: 'message.finished',
          payload: { conversation_id: 'conv-open', message_id: 'm-1' },
        }),
      ),
    );
    await flush();
    window.history.pushState({}, '', '/');
    expect(preferenceApi.getConversations).toHaveBeenCalledTimes(1);
  });

  it('refreshes the chat it shows while the user is away, for its unread mark', async () => {
    // Another tab or device answered it, or this tab streamed it unwatched:
    // the server marked it unread, and only the list says so.
    attention.attended = false;
    const store = makeStore('conv-open');
    store.dispatch(listed(['conv-open']));
    store.dispatch(
      sseEventReceived(
        ENVELOPE({
          id: 'evt-finished-away',
          type: 'message.finished',
          payload: { conversation_id: 'conv-open', message_id: 'm-1' },
        }),
      ),
    );
    await flush();
    attention.attended = true;
    expect(preferenceApi.getConversations).toHaveBeenCalledTimes(1);
  });

  const finished = (conversationId: string, id: string) =>
    ENVELOPE({
      id,
      type: 'message.finished',
      payload: { conversation_id: conversationId, message_id: 'm-1' },
    });

  it('keeps the list on screen when a background refresh fails', async () => {
    const store = makeStore('conv-open');
    store.dispatch(listed(['conv-old', 'conv-open']));
    (preferenceApi.getConversations as unknown as Mock).mockResolvedValue({
      data: null,
      loading: false,
    });
    store.dispatch(sseEventReceived(finished('conv-old', 'evt-fail')));
    await flush();
    expect(preferenceApi.getConversations).toHaveBeenCalledTimes(1);
    expect(
      store.getState().preference.conversations.data?.map((c) => c.id),
    ).toEqual(['conv-old', 'conv-open']);
  });

  it('folds a burst of events into one follow-up fetch, newest list last', async () => {
    const store = makeStore('conv-open');
    store.dispatch(listed(['conv-open']));
    const pending: Array<(names: string) => void> = [];
    (preferenceApi.getConversations as unknown as Mock).mockImplementation(
      () =>
        new Promise((resolve) =>
          pending.push((name) =>
            resolve({ data: [{ id: 'conv-a', name }], loading: false }),
          ),
        ),
    );
    for (let i = 0; i < 5; i += 1) {
      store.dispatch(sseEventReceived(finished('conv-a', `evt-burst-${i}`)));
    }
    await flush();
    expect(pending).toHaveLength(1);
    pending[0]('first');
    await flush();
    expect(pending).toHaveLength(2);
    pending[1]('second');
    await flush();
    expect(preferenceApi.getConversations).toHaveBeenCalledTimes(2);
    expect(store.getState().preference.conversations.data?.[0].name).toBe(
      'second',
    );
  });

  const renamed = (conversationId: string, previous?: string) =>
    ENVELOPE({
      id: `evt-rename-${conversationId}`,
      type: 'conversation.renamed',
      payload: {
        conversation_id: conversationId,
        name: 'Weather in Dubai',
        ...(previous === undefined ? {} : { previous }),
      },
    });

  it('keeps a name the user gave the chat over a late generated title', async () => {
    // A replay after the event stream dropped: the user renamed it meanwhile.
    const store = makeStore();
    store.dispatch(listed(['conv-old']));
    store.dispatch(
      prefSlice.actions.renameConversation({ id: 'conv-old', name: 'Mine' }),
    );
    store.dispatch(sseEventReceived(renamed('conv-old', 'conv-old')));
    await flush();
    expect(store.getState().preference.conversations.data?.[0].name).toBe(
      'Mine',
    );
  });

  it('swaps the fallback name it replaces for the generated title', async () => {
    const store = makeStore();
    store.dispatch(listed(['conv-old']));
    store.dispatch(sseEventReceived(renamed('conv-old', 'conv-old')));
    await flush();
    expect(store.getState().preference.conversations.data?.[0].name).toBe(
      'Weather in Dubai',
    );
  });

  it('refreshes the list for a title of a chat it does not list yet', async () => {
    const store = makeStore();
    store.dispatch(listed(['conv-old']));
    store.dispatch(sseEventReceived(renamed('conv-new', 'What is the')));
    await flush();
    expect(preferenceApi.getConversations).toHaveBeenCalledTimes(1);
  });

  it('swaps in the generated title when it is ready', async () => {
    const store = makeStore();
    store.dispatch(listed(['conv-old']));
    store.dispatch(
      sseEventReceived(
        ENVELOPE({
          id: 'evt-rename',
          type: 'conversation.renamed',
          payload: { conversation_id: 'conv-old', name: 'Weather in Dubai' },
        }),
      ),
    );
    await flush();
    expect(store.getState().preference.conversations.data?.[0].name).toBe(
      'Weather in Dubai',
    );
    expect(preferenceApi.getConversations).not.toHaveBeenCalled();
  });
});

describe('conversation listener — the list fetched when an answer ends', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('keeps a generated title that lands while that list is still on its way', async () => {
    // The title is saved after the answer, so the list asked for at its end
    // can read the fallback name and land after `conversation.renamed`.
    const fallback = 'what is the weather';
    let landStale!: (result: unknown) => void;
    const getConversations = preferenceApi.getConversations as unknown as Mock;
    getConversations.mockReset();
    getConversations
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            landStale = resolve;
          }),
      )
      .mockResolvedValue({
        data: [{ id: 'conv-1', name: 'Weather Today' }],
        loading: false,
      });
    vi.mocked(handleFetchAnswer).mockResolvedValue({
      answer: 'Sunny',
      thought: '',
      sources: [],
      toolCalls: [],
      conversationId: 'conv-1',
    } as never);

    const store = makeStore('conv-1');
    store.dispatch(
      prefSlice.actions.receiveConversations({
        data: [{ id: 'conv-1', name: fallback }] as never,
        loading: false,
      }),
    );
    store.dispatch(conversationSlice.actions.addQuery({ prompt: fallback }));
    await store.dispatch(
      fetchAnswer({ question: fallback, attachmentIds: [] }),
    );

    store.dispatch(
      sseEventReceived(
        ENVELOPE({
          id: 'evt-renamed',
          type: 'conversation.renamed',
          payload: {
            conversation_id: 'conv-1',
            name: 'Weather Today',
            previous: fallback,
          },
        }),
      ),
    );
    await new Promise((r) => setTimeout(r, 0));
    landStale({
      data: [{ id: 'conv-1', name: fallback }],
      loading: false,
    });
    for (let i = 0; i < 5; i += 1) await new Promise((r) => setTimeout(r, 0));

    expect(
      store.getState().preference.conversations.data?.map((c) => c.name),
    ).toEqual(['Weather Today']);
  });
});
