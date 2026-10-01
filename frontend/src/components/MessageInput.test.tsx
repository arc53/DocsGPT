import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
// The upload modal pulls in the whole ingest UI; the composer never opens it here.
vi.mock('../upload/Upload', () => ({ default: () => null }));
vi.mock('../modals/AddToolModal', () => ({ default: () => null }));
vi.mock('../connectors/SignInAgainNotice', () => ({
  default: () => null,
  useSignInAgain: () => ({ reconnect: vi.fn(), modals: null }),
}));

import connectorsReducer from '../connectors/connectorsSlice';
import notificationsReducer, {
  sseEventReceived,
} from '../notifications/notificationsSlice';
import { prefSlice } from '../preferences/preferenceSlice';
import type { RootState } from '../store';
import uploadReducer, {
  addAttachment,
  selectCompletedAttachments,
  selectSendableAttachmentIds,
  type Attachment,
} from '../upload/uploadSlice';
import userService from '../api/services/userService';
import MessageInput from './MessageInput';
import { ATTACHMENT_MAX_BYTES } from './message-input/attachmentUpload';
import { UPLOAD_STALL_TIMEOUT_MS } from './message-input/uploadStallGuard';

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

  body: FormData | null = null;

  open() {}
  setRequestHeader() {}
  send(body: FormData) {
    this.body = body;
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

  aborted = false;

  abort() {
    this.aborted = true;
    this.finish(this.onabort, 'abort');
  }

  /** The server answered with ``status`` and a JSON ``body``. */
  respond(status: number, body: unknown) {
    this.status = status;
    this.responseText = JSON.stringify(body);
    this.finish(this.onload, 'load');
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
    vi.restoreAllMocks();
  });

  const render = async (loading = false) => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <Provider store={store}>
            <MessageInput
              onSubmit={onSubmit}
              loading={loading}
              showSourceButton={false}
              showToolButton={false}
              autoFocus={false}
            />
          </Provider>
        </MemoryRouter>,
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

  const attachFile = (name: string) => attachFiles([name]);

  const attachFiles = async (names: string[]) => {
    const input = container.querySelector<HTMLInputElement>(
      'label input[type="file"]',
    )!;
    const files = names.map(
      (name) => new File(['%PDF-1.4'], name, { type: 'application/pdf' }),
    );
    Object.defineProperty(input, 'files', {
      value: files,
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

  it('keeps the composer in the natural tab order', async () => {
    await render();
    // A positive tabIndex jumps the page's tab order; the composer is the
    // default 0 and is reached where it sits.
    expect(textarea().hasAttribute('tabindex')).toBe(false);
  });

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

  it('sends the server id when the file finished before the upload returned', async () => {
    await render();
    await attachFile('small.pdf');
    const clientId = store.getState().upload.attachments[0].id;

    // The worker is faster than the response: its terminal event lands
    // while the row has no attachmentId to match it by.
    await act(async () => {
      store.dispatch(
        sseEventReceived({
          id: 'evt-1',
          type: 'attachment.completed',
          scope: { kind: 'attachment', id: 'srv-small' },
          payload: { token_count: 12 },
        }),
      );
    });
    await act(async () =>
      FakeXHR.instances[0].respond(200, {
        success: true,
        task_id: 'celery-1',
        attachment_id: 'srv-small',
      }),
    );

    const [row] = store.getState().upload.attachments;
    expect(row.status).toBe('completed');
    expect(row.id).toBe('srv-small');
    expect(row.id).not.toBe(clientId);
    expect(
      selectSendableAttachmentIds(store.getState() as unknown as RootState),
    ).toEqual(['srv-small']);
  });

  it("shows the worker's reason when the file failed before the upload returned", async () => {
    await render();
    await attachFile('locked.pdf');
    // The worker beats the response: the stash replay and the recent-events
    // walk can each apply it, and both must keep the reason.
    await act(async () => {
      store.dispatch(
        sseEventReceived({
          id: 'evt-failed',
          type: 'attachment.failed',
          scope: { kind: 'attachment', id: 'srv-locked' },
          payload: { error: 'File is password protected' },
        }),
      );
    });
    await act(async () =>
      FakeXHR.instances[0].respond(200, {
        task_id: 'celery-locked',
        attachment_id: 'srv-locked',
      }),
    );
    const [row] = store.getState().upload.attachments;
    expect(row.status).toBe('failed');
    expect(row.errorMessage).toBe('File is password protected');
  });

  const sentFileName = (xhr: FakeXHR) =>
    (xhr.body?.getAll('file') as File[]).map((f) => f.name);

  it('uploads each file in its own request, four at a time', async () => {
    await render();
    await attachFiles(['a.pdf', 'b.pdf', 'c.pdf', 'd.pdf', 'e.pdf', 'f.pdf']);

    expect(store.getState().upload.attachments).toHaveLength(6);
    expect(FakeXHR.instances).toHaveLength(4);
    expect(FakeXHR.instances.map(sentFileName)).toEqual([
      ['a.pdf'],
      ['b.pdf'],
      ['c.pdf'],
      ['d.pdf'],
    ]);

    await act(async () =>
      FakeXHR.instances[1].respond(200, {
        task_id: 'celery-b',
        attachment_id: 'srv-b',
      }),
    );
    await act(async () => {
      await vi.waitFor(() => expect(FakeXHR.instances).toHaveLength(5));
    });
    expect(sentFileName(FakeXHR.instances[4])).toEqual(['e.pdf']);

    const rowB = store
      .getState()
      .upload.attachments.find((a) => a.fileName === 'b.pdf')!;
    expect(rowB.status).toBe('processing');
    expect(rowB.attachmentId).toBe('srv-b');
  });

  it('fails only the file the server refused, with its reason', async () => {
    await render();
    await attachFiles(['big.pdf', 'fine.pdf']);

    await act(async () => {
      FakeXHR.instances[0].respond(413, {
        success: false,
        message: 'File exceeds the upload limit',
      });
      FakeXHR.instances[1].respond(200, {
        success: true,
        tasks: [{ task_id: 'celery-2', attachment_id: 'srv-fine' }],
      });
    });

    const rows = store.getState().upload.attachments;
    const big = rows.find((a) => a.fileName === 'big.pdf')!;
    const fine = rows.find((a) => a.fileName === 'fine.pdf')!;
    expect(big.status).toBe('failed');
    expect(big.errorMessage).toBe('File exceeds the upload limit');
    expect(fine.status).toBe('processing');
    expect(fine.attachmentId).toBe('srv-fine');
  });

  it('does not upload a queued file the user removed', async () => {
    await render();
    await attachFiles(['a.pdf', 'b.pdf', 'c.pdf', 'd.pdf', 'e.pdf']);
    const queued = store
      .getState()
      .upload.attachments.find((a) => a.fileName === 'e.pdf')!;
    await act(async () => {
      store.dispatch({ type: 'upload/removeAttachment', payload: queued.id });
    });

    await act(async () => FakeXHR.instances[0].failNetwork());
    // Give the queue a chance to start the next upload, if any.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(FakeXHR.instances).toHaveLength(4);
  });

  it('stops the upload of a file the user removed mid-way', async () => {
    await render();
    await attachFiles(['a.pdf', 'b.pdf']);
    const [a, b] = store.getState().upload.attachments;
    await act(async () => {
      store.dispatch({ type: 'upload/removeAttachment', payload: a.id });
    });

    expect(FakeXHR.instances[0].aborted).toBe(true);
    expect(FakeXHR.instances[1].aborted).toBe(false);
    expect(store.getState().upload.attachments.map((x) => x.id)).toEqual([
      b.id,
    ]);
  });

  const oversized = (name: string) => {
    const file = new File(['%PDF-1.4'], name, { type: 'application/pdf' });
    Object.defineProperty(file, 'size', { value: ATTACHMENT_MAX_BYTES + 1 });
    return file;
  };

  const expectRefusedAsTooLarge = (name: string) => {
    const row = store
      .getState()
      .upload.attachments.find((a) => a.fileName === name)!;
    expect(row.status).toBe('failed');
    expect(row.errorMessage).toBe('conversation.attachments.tooLarge');
  };

  it('refuses a picked file over the size limit with a failed chip', async () => {
    await render();
    const input = container.querySelector<HTMLInputElement>(
      'label input[type="file"]',
    )!;
    Object.defineProperty(input, 'files', {
      value: [
        oversized('huge.pdf'),
        new File(['%PDF-1.4'], 'ok.pdf', { type: 'application/pdf' }),
      ],
      configurable: true,
    });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await act(async () => {
      await vi.waitFor(() => expect(FakeXHR.instances).toHaveLength(1));
    });

    expectRefusedAsTooLarge('huge.pdf');
    expect(sentFileName(FakeXHR.instances[0])).toEqual(['ok.pdf']);
  });

  it('refuses a dropped file over the size limit instead of ignoring it', async () => {
    await render();
    const file = oversized('dropped.pdf');
    const dataTransfer = {
      files: [file],
      items: [{ kind: 'file', type: file.type, getAsFile: () => file }],
      types: ['Files'],
    };
    const drop = new Event('drop', { bubbles: true });
    Object.defineProperty(drop, 'dataTransfer', { value: dataTransfer });
    await act(async () => {
      container.querySelector('#message-input')!.dispatchEvent(drop);
    });
    await act(async () => {
      await vi.waitFor(() =>
        expect(store.getState().upload.attachments).toHaveLength(1),
      );
    });

    expectRefusedAsTooLarge('dropped.pdf');
    expect(FakeXHR.instances).toHaveLength(0);
  });

  const attachmentProgress = (id: string, current: number, n: number) =>
    sseEventReceived({
      id: `${id}-progress-${n}`,
      type: 'attachment.progress',
      scope: { kind: 'attachment', id },
      payload: { current },
    });

  const storeSlow = async () => {
    await render();
    await attachFile('bundle.zip');
    await act(async () =>
      FakeXHR.instances[0].respond(200, {
        success: true,
        task_id: 'celery-slow',
        attachment_id: 'srv-slow',
      }),
    );
    expect(store.getState().upload.attachments[0].status).toBe('processing');
  };

  it('keeps a slow file processing while its progress keeps arriving', async () => {
    vi.useFakeTimers();
    await storeSlow();

    // Twenty minutes of work, a sign of life every four: never cut off,
    // even when an event does not move the bar.
    for (let n = 0; n < 5; n++) {
      await act(async () => {
        vi.advanceTimersByTime(4 * 60_000);
      });
      await act(async () => {
        store.dispatch(attachmentProgress('srv-slow', 50, n));
      });
    }
    expect(store.getState().upload.attachments[0].status).toBe('processing');
  });

  it('fails a processing file after five minutes without progress', async () => {
    vi.useFakeTimers();
    await storeSlow();
    await act(async () => {
      store.dispatch(attachmentProgress('srv-slow', 40, 1));
    });

    await act(async () => {
      vi.advanceTimersByTime(5 * 60_000 - 1);
    });
    expect(store.getState().upload.attachments[0].status).toBe('processing');

    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(store.getState().upload.attachments[0].status).toBe('failed');
  });

  const taskStatus = (status: string, result: unknown = null) =>
    vi
      .spyOn(userService, 'getTaskStatus')
      .mockImplementation(
        async () =>
          new Response(JSON.stringify({ status, result }), { status: 200 }),
      );

  const statusOf = () => store.getState().upload.attachments[0].status;

  it('waits for a busy worker to start the file before timing it', async () => {
    vi.useFakeTimers();
    const getTaskStatus = taskStatus('PENDING');
    await storeSlow();

    // Forty files queue behind each other: this one has heard nothing yet.
    await act(async () => {
      vi.advanceTimersByTime(10 * 60_000 - 1);
    });
    expect(statusOf()).toBe('processing');
    expect(getTaskStatus).not.toHaveBeenCalled();

    // After ten quiet minutes it asks, and a queued file keeps waiting.
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(getTaskStatus).toHaveBeenCalledWith('celery-slow', null);
    expect(statusOf()).toBe('processing');

    // The worker takes it: from now on five quiet minutes fail it.
    await act(async () => {
      store.dispatch(attachmentProgress('srv-slow', 10, 0));
    });
    await act(async () => {
      vi.advanceTimersByTime(5 * 60_000 - 1);
    });
    expect(statusOf()).toBe('processing');
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(statusOf()).toBe('failed');
  });

  it('times a file the status says a worker took', async () => {
    vi.useFakeTimers();
    taskStatus('STARTED');
    await storeSlow();
    await act(async () => {
      vi.advanceTimersByTime(10 * 60_000);
    });
    expect(statusOf()).toBe('processing');
    await act(async () => {
      vi.advanceTimersByTime(5 * 60_000);
    });
    expect(statusOf()).toBe('failed');
  });

  it('fails the file with the reason the status reports', async () => {
    vi.useFakeTimers();
    taskStatus('FAILURE', 'Could not parse the file');
    await storeSlow();
    await act(async () => {
      vi.advanceTimersByTime(10 * 60_000);
    });
    const [row] = store.getState().upload.attachments;
    expect(row.status).toBe('failed');
    expect(row.errorMessage).toBe('Could not parse the file');
  });

  it('gives up on a file no worker took within an hour', async () => {
    vi.useFakeTimers();
    taskStatus('PENDING');
    await storeSlow();
    // Async: each check re-arms the next one once its answer is in.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 60_000 - 1);
    });
    expect(statusOf()).toBe('processing');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(statusOf()).toBe('failed');
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
