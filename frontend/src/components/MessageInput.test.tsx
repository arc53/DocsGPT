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
import { UPLOAD_STALL_TIMEOUT_MS } from './message-input/uploadStallGuard';

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

/** Just enough of XMLHttpRequest for the composer's upload paths. */
class FakeXHR extends EventTarget {
  static instances: FakeXHR[] = [];

  upload = new EventTarget();
  status = 0;
  responseText = '';
  timeout = 0;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  ontimeout: (() => void) | null = null;

  open() {}
  setRequestHeader() {}
  send() {
    FakeXHR.instances.push(this);
  }

  private finish(handler: (() => void) | null, type: string) {
    handler?.();
    this.dispatchEvent(new Event(type));
    this.dispatchEvent(new Event('loadend'));
  }

  /** What Android Chrome reported: no response, status 0. */
  failNetwork() {
    this.status = 0;
    this.finish(this.onerror, 'error');
  }

  abort() {
    this.finish(this.onabort, 'abort');
  }
}

describe('MessageInput send with a failed attachment', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: TestStore;
  let onSubmit: ReturnType<typeof vi.fn<(text: string) => void>>;
  const realXHR = globalThis.XMLHttpRequest;

  beforeEach(() => {
    localStorage.clear();
    FakeXHR.instances = [];
    globalThis.XMLHttpRequest = FakeXHR as unknown as typeof XMLHttpRequest;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    store = makeStore();
    onSubmit = vi.fn<(text: string) => void>();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    globalThis.XMLHttpRequest = realXHR;
    vi.useRealTimers();
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

  const attachFile = async (name: string) => {
    const input = container.querySelector<HTMLInputElement>(
      'label input[type="file"]',
    )!;
    const file = new File(['%PDF-1.4'], name, { type: 'application/pdf' });
    Object.defineProperty(input, 'files', {
      value: [file],
      configurable: true,
    });
    const sent = FakeXHR.instances.length;
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    // partitionAttachmentFiles sniffs the file asynchronously.
    await act(async () => {
      await vi.waitFor(() =>
        expect(FakeXHR.instances.length).toBeGreaterThan(sent),
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

  it('sends when the only attachment failed on the network', async () => {
    await render();
    await attachFile('scan.pdf');
    expect(FakeXHR.instances).toHaveLength(1);

    await act(async () => FakeXHR.instances[0].failNetwork());
    const [chip] = store.getState().upload.attachments;
    expect(chip.status).toBe('failed');
    expect(chip.errorMessage).toBe('conversation.attachments.uploadFailed');

    await type('Summarise this');
    await pressEnter();

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith('Summarise this');
    expect(store.getState().upload.attachments).toEqual([]);
  });

  it('shows no send-blocked alert after a failed send attempt', async () => {
    store.dispatch(addAttachment(att({ id: 'bad-1', status: 'failed' })));
    await render();

    await type('hello');
    await pressEnter();

    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('fails a stalled upload and then flushes the queued send', async () => {
    vi.useFakeTimers();
    await render();
    await attachFile('huge.pdf');
    expect(store.getState().upload.attachments[0].status).toBe('uploading');

    await type('Is it done?');
    await pressEnter();
    // Pending: the send is queued, not dropped.
    expect(onSubmit).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(UPLOAD_STALL_TIMEOUT_MS);
    });

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith('Is it done?');
    expect(store.getState().upload.attachments).toEqual([]);
  });

  it('keeps a queued question while another answer is streaming', async () => {
    store.dispatch(addAttachment(att({ status: 'processing', progress: 30 })));
    await render();
    await type('Queued question');
    await pressEnter();
    expect(onSubmit).not.toHaveBeenCalled();

    // A retry starts streaming, then the file settles.
    await render(true);
    await act(async () => {
      store.dispatch({
        type: 'upload/updateAttachment',
        payload: { id: 'ok-1', updates: { status: 'completed' } },
      });
    });

    expect(onSubmit).not.toHaveBeenCalled();
    expect(textarea().value).toBe('Queued question');

    // The stream ends: the held send goes out.
    await render(false);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith('Queued question');
  });
});
