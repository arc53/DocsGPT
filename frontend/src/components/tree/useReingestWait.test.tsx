import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

import notificationsReducer, {
  sseEventReceived,
  type SSEEvent,
} from '../../notifications/notificationsSlice';
import { type ReingestTerminal, useReingestSseWaiter } from './useReingestWait';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

type Waiter = ReturnType<typeof useReingestSseWaiter>;

const makeStore = () =>
  configureStore({ reducer: { notifications: notificationsReducer } });

let seq = 0;
const terminal = (
  type: 'completed' | 'failed',
  ts: number,
  payload: Record<string, unknown> = {},
): SSEEvent => ({
  id: `${++seq}-0`,
  type: `source.ingest.${type}`,
  ts: new Date(ts).toISOString(),
  scope: { kind: 'source', id: 'src-1' },
  payload,
});

describe('useReingestSseWaiter', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;
  let waiter: Waiter;

  const Probe = () => {
    waiter = useReingestSseWaiter();
    return null;
  };

  const mount = (preload: SSEEvent[] = []) => {
    store = makeStore();
    for (const event of preload) store.dispatch(sseEventReceived(event));
    act(() => {
      root.render(
        <Provider store={store}>
          <Probe />
        </Provider>,
      );
    });
  };

  /** Starts a wait and records its result once it settles. */
  const start = (startedAt: number, taskId?: string) => {
    const result: { value: ReingestTerminal | null } = { value: null };
    void waiter
      .waitForTerminal('src-1', startedAt, { taskId })
      .then((value) => (result.value = value));
    return result;
  };

  const flush = () => act(async () => undefined);

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('finishes on a new terminal event even when the server clock is behind', async () => {
    mount();
    const startedAt = Date.now();
    const wait = start(startedAt);
    // The server's clock runs a minute behind this browser's.
    act(() => {
      store.dispatch(
        sseEventReceived(terminal('completed', startedAt - 60_000)),
      );
    });
    await flush();
    expect(wait.value).toBe('completed');
  });

  it('ignores a terminal event this tab had before the operation started', async () => {
    mount([terminal('completed', Date.now() + 60_000)]);
    const wait = start(Date.now());
    await flush();
    expect(wait.value).toBeNull();
    act(() => {
      store.dispatch(sseEventReceived(terminal('failed', Date.now())));
    });
    await flush();
    expect(wait.value).toBe('failed');
  });

  it('keeps overlapping waits apart', async () => {
    mount();
    const first = start(Date.now());
    const second = start(Date.now());
    act(() => {
      store.dispatch(sseEventReceived(terminal('completed', Date.now())));
    });
    await flush();
    expect(first.value).toBe('completed');
    expect(second.value).toBe('completed');
  });

  it('matches on the task id when the event carries one', async () => {
    mount();
    const first = start(Date.now(), 'task-a');
    const second = start(Date.now(), 'task-b');
    act(() => {
      store.dispatch(
        sseEventReceived(terminal('failed', Date.now(), { task_id: 'task-b' })),
      );
    });
    await flush();
    expect(first.value).toBeNull();
    expect(second.value).toBe('failed');
    act(() => {
      store.dispatch(
        sseEventReceived(
          terminal('completed', Date.now(), { task_id: 'task-a' }),
        ),
      );
    });
    await flush();
    expect(first.value).toBe('completed');
  });

  it("waitForChange carries a failure's reason", async () => {
    mount();
    const result: { value: unknown } = { value: null };
    void waiter
      .waitForChange('src-1', Date.now(), { taskId: 'task-a' })
      .then((value) => (result.value = value));
    act(() => {
      store.dispatch(
        sseEventReceived(
          terminal('failed', Date.now(), { task_id: 'task-a', reason: 'busy' }),
        ),
      );
    });
    await flush();
    expect(result.value).toEqual({
      terminal: 'failed',
      reason: 'busy',
      failedPages: [],
    });

    const plain: { value: unknown } = { value: null };
    void waiter
      .waitForChange('src-1', Date.now(), { taskId: 'task-b' })
      .then((value) => (plain.value = value));
    act(() => {
      store.dispatch(
        sseEventReceived(
          terminal('completed', Date.now(), { task_id: 'task-b' }),
        ),
      );
    });
    await flush();
    expect(plain.value).toEqual({
      terminal: 'completed',
      reason: null,
      failedPages: [],
    });
  });

  it('waitForChange carries the pages a finished add could not fetch', async () => {
    mount();
    const result: { value: unknown } = { value: null };
    void waiter
      .waitForChange('src-1', Date.now(), { taskId: 'task-a' })
      .then((value) => (result.value = value));
    act(() => {
      store.dispatch(
        sseEventReceived(
          terminal('completed', Date.now(), {
            task_id: 'task-a',
            failed_pages: ['https://docs.x.io/a', 7, '', 'https://docs.x.io/b'],
          }),
        ),
      );
    });
    await flush();
    expect(result.value).toEqual({
      terminal: 'completed',
      reason: null,
      failedPages: ['https://docs.x.io/a', 'https://docs.x.io/b'],
    });
  });

  it('settles pending waits when the component unmounts', async () => {
    mount();
    const wait = start(Date.now());
    act(() => root.unmount());
    await flush();
    expect(wait.value).toBe('unmounted');
    root = createRoot(container);
  });
});
