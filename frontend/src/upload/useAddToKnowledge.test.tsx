import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
  }),
}));

const createSourceFromAttachments = vi.hoisted(() => vi.fn());
vi.mock('../api/services/userService', () => ({
  default: { createSourceFromAttachments },
}));

const getDocs = vi.hoisted(() => vi.fn());
vi.mock('../preferences/preferenceApi', () => ({ getDocs }));

import notificationsReducer, {
  sseEventReceived,
} from '../notifications/notificationsSlice';
import preferenceReducer, {
  setSelectedDocs,
} from '../preferences/preferenceSlice';
import uploadReducer from './uploadSlice';
import {
  knowledgeIdempotencyKey,
  useAddToKnowledge,
} from './useAddToKnowledge';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

type HookResult = ReturnType<typeof useAddToKnowledge>;

const makeStore = () =>
  configureStore({
    reducer: {
      upload: uploadReducer,
      preference: preferenceReducer,
      notifications: notificationsReducer,
    },
  });

const okResponse = (body: unknown) => ({
  ok: true,
  status: 200,
  json: async () => body,
});

describe('useAddToKnowledge', () => {
  let container: HTMLDivElement;
  let root: Root;
  let hook: HookResult;
  let store: ReturnType<typeof makeStore>;

  function Harness() {
    hook = useAddToKnowledge();
    return null;
  }

  beforeEach(async () => {
    createSourceFromAttachments.mockReset();
    getDocs.mockReset();
    store = makeStore();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () =>
      root.render(
        <Provider store={store}>
          <Harness />
        </Provider>,
      ),
    );
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const files = [
    { id: 'att-1', fileName: 'report.pdf' },
    { id: 'att-2', fileName: 'data.csv' },
    { id: 'att-3', fileName: 'scan.png' },
  ];

  it('asks the server for a source named after the files and tracks its ingest', async () => {
    createSourceFromAttachments.mockResolvedValue(
      okResponse({ success: true, task_id: 'task-9', source_id: 'src-9' }),
    );

    let accepted = false;
    await act(async () => {
      accepted = await hook.addToKnowledge(files);
    });

    expect(accepted).toBe(true);
    expect(createSourceFromAttachments).toHaveBeenCalledWith(
      {
        attachment_ids: ['att-1', 'att-2', 'att-3'],
        name: 'conversation.attachments.knowledgeName:{"name":"report.pdf","count":2}',
      },
      null,
      expect.any(String),
    );
    const task = store.getState().upload.tasks[0];
    expect(task).toMatchObject({
      sourceId: 'src-9',
      taskId: 'task-9',
      status: 'training',
    });
    expect(hook.error).toBeNull();
  });

  it('sends one Idempotency-Key per file set, so a repeat gets the first source', async () => {
    createSourceFromAttachments.mockResolvedValue(
      okResponse({ success: true, task_id: 't', source_id: 's' }),
    );
    const set = [
      { id: 'key-a', fileName: 'a.pdf' },
      { id: 'key-b', fileName: 'b.pdf' },
    ];
    await act(async () => {
      await hook.addToKnowledge(set);
      await hook.addToKnowledge([...set].reverse());
      await hook.addToKnowledge([set[0]]);
    });
    const keys = createSourceFromAttachments.mock.calls.map((call) => call[2]);
    expect(keys[0]).toEqual(expect.any(String));
    expect(keys[0]).not.toBe('');
    // The same files in another order are the same set.
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
  });

  it('names a single file after itself', async () => {
    createSourceFromAttachments.mockResolvedValue(
      okResponse({ success: true, task_id: 't', source_id: 's' }),
    );
    await act(async () => {
      await hook.addToKnowledge([files[0]]);
    });
    expect(createSourceFromAttachments.mock.calls[0][0].name).toBe(
      'report.pdf',
    );
  });

  it('selects the new source for the chat once it is ingested', async () => {
    createSourceFromAttachments.mockResolvedValue(
      okResponse({ success: true, task_id: 'task-9', source_id: 'src-9' }),
    );
    const earlier = { id: 'src-1', name: 'Handbook', date: '', model: '' };
    const created = {
      id: 'src-9',
      name: 'report.pdf and 2 more',
      date: '',
      model: '',
    };
    getDocs.mockResolvedValue([earlier, created]);
    store.dispatch(setSelectedDocs([earlier]));

    await act(async () => {
      await hook.addToKnowledge(files);
    });
    await act(async () => {
      store.dispatch(
        sseEventReceived({
          id: 'e1',
          type: 'source.ingest.completed',
          scope: { kind: 'source', id: 'src-9' },
          payload: {},
        }),
      );
    });

    expect(getDocs).toHaveBeenCalled();
    expect(store.getState().preference.selectedDocs).toEqual([
      earlier,
      created,
    ]);
    expect(store.getState().preference.sourceDocs).toEqual([earlier, created]);
  });

  it('leaves the selection alone when the ingest fails', async () => {
    createSourceFromAttachments.mockResolvedValue(
      okResponse({ success: true, task_id: 'task-9', source_id: 'src-9' }),
    );
    await act(async () => {
      await hook.addToKnowledge(files);
    });
    await act(async () => {
      store.dispatch(
        sseEventReceived({
          id: 'e2',
          type: 'source.ingest.failed',
          scope: { kind: 'source', id: 'src-9' },
          payload: { error: 'boom' },
        }),
      );
    });
    expect(getDocs).not.toHaveBeenCalled();
    expect(store.getState().preference.selectedDocs).toEqual([]);
  });

  it('reports a refused request inline and leaves no task behind', async () => {
    createSourceFromAttachments.mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ success: false, message: 'Attachment not found' }),
    });

    let accepted = true;
    await act(async () => {
      accepted = await hook.addToKnowledge(files);
    });

    expect(accepted).toBe(false);
    expect(hook.error).toBe('conversation.attachments.knowledgeFailed');
    expect(store.getState().upload.tasks).toEqual([]);
    expect(hook.pending).toBe(false);
  });
});

describe('knowledgeIdempotencyKey', () => {
  // sha256("att-a\natt-b")
  const SHA256_OF_A_B =
    '88dd9c3c846f0c98f4d080d7e14e0b8dc02a8240dc7a2e73f5222263a25af65c';

  it('derives the key from the sorted ids, so a reload sends the same one', async () => {
    // Nothing kept in memory: the same files give the same key on any page.
    await expect(knowledgeIdempotencyKey(['att-b', 'att-a'])).resolves.toBe(
      `attachments-knowledge:${SHA256_OF_A_B}`,
    );
    await expect(
      knowledgeIdempotencyKey(['att-a', 'att-b', 'att-a']),
    ).resolves.toBe(await knowledgeIdempotencyKey(['att-b', 'att-a']));
  });

  it('still derives a stable key where Web Crypto is unavailable', async () => {
    // crypto.subtle exists only in secure contexts (not plain-HTTP hosts).
    const subtle = vi
      .spyOn(globalThis.crypto, 'subtle', 'get')
      .mockReturnValue(undefined as unknown as SubtleCrypto);
    try {
      const ids = Array.from({ length: 60 }, (_, i) => `att-${i}`);
      const key = await knowledgeIdempotencyKey(ids);
      expect(key).toMatch(/^attachments-knowledge:h:[0-9a-f]{56}$/);
      expect(key.length).toBeLessThanOrEqual(256);
      expect(await knowledgeIdempotencyKey([...ids].reverse())).toBe(key);
      expect(await knowledgeIdempotencyKey(ids.slice(1))).not.toBe(key);
    } finally {
      subtle.mockRestore();
    }
  });
});
