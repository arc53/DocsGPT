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

describe('listener middleware export hygiene', () => {
  it('exports the listener middleware so the store can wire it', () => {
    expect(conversationListenerMiddleware).toBeDefined();
    expect(typeof conversationListenerMiddleware.middleware).toBe('function');
  });

  it('still exports the slice actions consumers rely on', () => {
    expect(typeof setConversation).toBe('function');
  });
});
