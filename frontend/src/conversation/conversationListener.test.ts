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
import {
  conversationListenerMiddleware,
  conversationSlice,
  setConversation,
} from './conversationSlice';

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
    attachmentBudgetShare: null,
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

  it('never interrupts the stream of the turn that moved on', async () => {
    const store = makeStore('conv-1', 'loading');
    store.dispatch(sseEventReceived(CLEARED('moved_on')));
    await settle();
    expect(conversationService.getConversation).not.toHaveBeenCalled();
    expect(store.getState().conversation.status).toBe('loading');
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
