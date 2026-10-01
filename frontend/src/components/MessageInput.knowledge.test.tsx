import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../upload/Upload', () => ({ default: () => null }));
vi.mock('../connectors/SignInAgainNotice', () => ({
  default: () => null,
  useSignInAgain: () => ({ reconnect: vi.fn(), modals: null }),
}));

const createSourceFromAttachments = vi.hoisted(() => vi.fn());
vi.mock('../api/services/userService', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../api/services/userService')>();
  return {
    default: { ...actual.default, createSourceFromAttachments },
  };
});

import connectorsReducer from '../connectors/connectorsSlice';
import type { Model } from '../models/types';
import notificationsReducer from '../notifications/notificationsSlice';
import {
  prefSlice,
  setAttachmentBudgetShare,
  setSelectedModel,
} from '../preferences/preferenceSlice';
import uploadReducer, {
  addAttachment,
  type Attachment,
} from '../upload/uploadSlice';
import MessageInput from './MessageInput';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const makeStore = () =>
  configureStore({
    reducer: {
      preference: prefSlice.reducer,
      upload: uploadReducer,
      notifications: notificationsReducer,
      connectors: connectorsReducer,
    },
  });

const model = (over: Partial<Model> = {}): Model => ({
  id: 'm',
  value: 'm',
  provider: 'p',
  display_name: 'Model',
  context_window: 10_000,
  supported_attachment_types: [],
  supports_tools: true,
  supports_structured_output: false,
  supports_streaming: true,
  ...over,
});

const att = (over: Partial<Attachment>): Attachment => ({
  id: 'a',
  fileName: 'a.pdf',
  progress: 100,
  status: 'completed',
  taskId: 't',
  ...over,
});

describe('MessageInput Knowledge hint', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;

  beforeEach(() => {
    createSourceFromAttachments.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    store = makeStore();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (showSourceButton = true) => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MessageInput
            onSubmit={vi.fn()}
            loading={false}
            showSourceButton={showSourceButton}
            showToolButton={false}
            autoFocus={false}
          />
        </Provider>,
      );
    });
  };

  const addFiles = (...tokens: number[]) =>
    tokens.forEach((token_count, i) =>
      store.dispatch(
        addAttachment(
          att({ id: `srv-${i}`, fileName: `f${i}.pdf`, token_count }),
        ),
      ),
    );

  it('stays quiet while the files fit the budget', async () => {
    store.dispatch(setSelectedModel(model()));
    addFiles(2_000, 2_000);
    await render();
    expect(container.textContent).not.toContain('knowledgeHint');
  });

  it('offers Knowledge once the files pass the share of the window', async () => {
    store.dispatch(setSelectedModel(model()));
    store.dispatch(setAttachmentBudgetShare(0.3));
    addFiles(2_000, 2_000);
    await render();
    expect(container.textContent).toContain(
      'conversation.attachments.knowledgeHint',
    );
  });

  it('is not offered where the chat has no Knowledge picker', async () => {
    store.dispatch(setSelectedModel(model({ context_window: 1_000 })));
    addFiles(2_000);
    await render(false);
    expect(container.textContent).not.toContain('knowledgeHint');
  });

  it('turns the files into Knowledge and takes them out of the composer', async () => {
    createSourceFromAttachments.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, task_id: 't9', source_id: 's9' }),
    });
    store.dispatch(setSelectedModel(model({ context_window: 1_000 })));
    addFiles(800, 800);
    await render();

    const button = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('conversation.attachments.addAsKnowledge'),
    );
    expect(button).toBeDefined();
    await act(async () => button?.click());

    expect(createSourceFromAttachments.mock.calls[0][0].attachment_ids).toEqual(
      ['srv-0', 'srv-1'],
    );
    expect(store.getState().upload.attachments).toEqual([]);
    expect(store.getState().upload.tasks[0]).toMatchObject({
      sourceId: 's9',
      status: 'training',
    });
  });
});
