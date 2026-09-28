import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
// The upload modal pulls in the whole ingest UI; the composer never opens it here.
vi.mock('../upload/Upload', () => ({ default: () => null }));

import notificationsReducer from '../notifications/notificationsSlice';
import { prefSlice } from '../preferences/preferenceSlice';
import type { RootState } from '../store';
import uploadReducer, {
  addAttachment,
  selectCompletedAttachments,
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
    },
  });

type TestStore = ReturnType<typeof makeStore>;

const att = (over: Partial<Attachment> = {}): Attachment => ({
  id: 'ok-1',
  fileName: 'notes.pdf',
  progress: 100,
  status: 'completed',
  taskId: 't1',
  ...over,
});

describe('MessageInput send with a failed attachment', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: TestStore;
  let onSubmit: ReturnType<typeof vi.fn<(text: string) => void>>;

  beforeEach(() => {
    localStorage.clear();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    store = makeStore();
    onSubmit = vi.fn<(text: string) => void>();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (loading = false) => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MessageInput
            onSubmit={onSubmit}
            loading={loading}
            showSourceButton={false}
            showToolButton={false}
            autoFocus={false}
          />
        </Provider>,
      );
    });
  };

  const textarea = () =>
    container.querySelector<HTMLTextAreaElement>('#message-input')!;

  const type = async (text: string) => {
    const el = textarea();
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        'value',
      )!.set!;
      setter.call(el, text);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  const pressEnter = async () => {
    await act(async () => {
      textarea().dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
  };

  it('sends the question and drops the failed file', async () => {
    store.dispatch(addAttachment(att()));
    store.dispatch(
      addAttachment(
        att({ id: 'bad-1', fileName: 'broken.pdf', status: 'failed' }),
      ),
    );
    let idsAtSubmit: string[] = [];
    onSubmit.mockImplementation(() => {
      idsAtSubmit = selectCompletedAttachments(
        store.getState() as unknown as RootState,
      ).map((a) => a.id);
    });
    await render();

    await type('What does the contract say?');
    await pressEnter();

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith('What does the contract say?');
    expect(idsAtSubmit).toEqual(['ok-1']);
    expect(store.getState().upload.attachments.map((a) => a.id)).toEqual([
      'ok-1',
    ]);
    expect(textarea().value).toBe('');
  });

  it('shows no send-blocked alert after a failed send attempt', async () => {
    store.dispatch(addAttachment(att({ id: 'bad-1', status: 'failed' })));
    await render();

    await type('hello');
    await pressEnter();

    expect(container.querySelector('[role="alert"]')).toBeNull();
  });
});
