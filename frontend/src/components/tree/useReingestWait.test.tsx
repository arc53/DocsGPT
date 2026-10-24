import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

import notificationsReducer, {
  sseEventReceived,
  type SSEEvent,
} from '../../notifications/notificationsSlice';
import { type ReingestOutcome, useReingestSseWaiter } from './useReingestWait';

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

  /** Starts a wait and records its outcome once it settles. */
  const startChange = (taskId?: string, startedAt = Date.now()) => {
    const result: { value: ReingestOutcome | null } = { value: null };
    void waiter
      .waitForChange('src-1', startedAt, { taskId })
      .then((value) => (result.value = value));
    return result;
  };

  /** A terminal event for the source arrives, stamped `ts` by the server. */
  const emit = async (
    type: 'completed' | 'failed',
    payload: Record<string, unknown> = {},
    ts = Date.now(),
  ) => {
    act(() => {
      store.dispatch(sseEventReceived(terminal(type, ts, payload)));
    });
    await act(async () => undefined);
  };

  const outcome = (extra: Partial<ReingestOutcome> = {}): ReingestOutcome => ({
    terminal: 'completed',
    reason: null,
    failedPages: [],
    paths: null,
    ...extra,
  });

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
    const wait = startChange();
    // The server's clock runs a minute behind this browser's.
    await emit('completed', {}, Date.now() - 60_000);
    expect(wait.value?.terminal).toBe('completed');
  });

  it('ignores a terminal event this tab had before the operation started', async () => {
    mount([terminal('completed', Date.now() + 60_000)]);
    const wait = startChange();
    await act(async () => undefined);
    expect(wait.value).toBeNull();
    await emit('failed');
    expect(wait.value?.terminal).toBe('failed');
  });

  it('keeps overlapping waits apart', async () => {
    mount();
    const first = startChange();
    const second = startChange();
    await emit('completed');
    expect(first.value?.terminal).toBe('completed');
    expect(second.value?.terminal).toBe('completed');
  });

  it('matches on the task id when the event carries one', async () => {
    mount();
    const first = startChange('task-a');
    const second = startChange('task-b');
    await emit('failed', { task_id: 'task-b' });
    expect(first.value).toBeNull();
    expect(second.value?.terminal).toBe('failed');
    await emit('completed', { task_id: 'task-a' });
    expect(first.value?.terminal).toBe('completed');
  });

  it.each([
    ['a plain finish', 'completed', {}, outcome()],
    [
      "a failure's reason",
      'failed',
      { reason: 'busy' },
      outcome({ terminal: 'failed', reason: 'busy' }),
    ],
    [
      'the pages a finished add could not fetch',
      'completed',
      {
        failed_pages: ['https://docs.x.io/a', 7, '', 'https://docs.x.io/b'],
      },
      outcome({
        failedPages: ['https://docs.x.io/a', 'https://docs.x.io/b'],
      }),
    ],
    [
      'the tree paths a page change wrote or removed',
      'completed',
      { paths: ['extra.md', 7, '', 'Deploying/Docker.md'] },
      outcome({ paths: ['extra.md', 'Deploying/Docker.md'] }),
    ],
    [
      'a page change that touched no page',
      'completed',
      { paths: [] },
      outcome({ paths: [] }),
    ],
  ] as const)('carries %s', async (_, type, payload, expected) => {
    mount();
    const wait = startChange('task-a');
    await emit(type, { task_id: 'task-a', ...payload });
    expect(wait.value).toEqual(expected);
  });

  it('settles pending waits when the component unmounts', async () => {
    mount();
    const wait = startChange();
    act(() => root.unmount());
    await act(async () => undefined);
    expect(wait.value?.terminal).toBe('unmounted');
    root = createRoot(container);
  });
});
