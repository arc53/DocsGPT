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
import { useAddToKnowledge } from './useAddToKnowledge';

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
    );
    const task = store.getState().upload.tasks[0];
    expect(task).toMatchObject({
      sourceId: 'src-9',
      taskId: 'task-9',
      status: 'training',
    });
    expect(hook.error).toBeNull();
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
