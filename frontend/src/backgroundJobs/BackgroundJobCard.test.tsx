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

const service = vi.hoisted(() => ({
  getJob: vi.fn(),
  listJobs: vi.fn(),
  cancelJob: vi.fn(),
}));
vi.mock('../api/services/backgroundService', () => ({ default: service }));

import type { ToolCallsType } from '../conversation/types';
import actionToastReducer from '../notifications/actionToastSlice';
import notificationsReducer, {
  sseEventReceived,
} from '../notifications/notificationsSlice';
import BackgroundJobCard, {
  effectiveJobStatus,
  elapsedSeconds,
  formatElapsed,
  JOB_POLL_MS,
} from './BackgroundJobCard';
import backgroundReducer, { type BackgroundJob } from './backgroundSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const CALL: ToolCallsType = {
  tool_name: 'code_executor',
  action_name: 'run_code',
  call_id: 'call-1',
  arguments: {},
  status: 'pending',
  job_id: 'j1',
};

const t = (key: string, opts?: Record<string, unknown>) =>
  `${key}:${JSON.stringify(opts)}`;

describe('BackgroundJobCard helpers', () => {
  const job = (over: Partial<BackgroundJob>): BackgroundJob => ({
    job_id: 'j1',
    status: 'working',
    receivedAt: 0,
    ...over,
  });

  it('prefers the live job, then the patched outcome, then the call status', () => {
    expect(effectiveJobStatus(CALL, job({ status: 'failed' }))).toBe('failed');
    expect(effectiveJobStatus({ ...CALL, job_status: 'lost' }, undefined)).toBe(
      'lost',
    );
    expect(
      effectiveJobStatus({ ...CALL, status: 'completed' }, undefined),
    ).toBe('completed');
    expect(effectiveJobStatus({ ...CALL, status: 'error' }, undefined)).toBe(
      'failed',
    );
    expect(
      effectiveJobStatus({ ...CALL, job_status: 'bogus' }, undefined),
    ).toBe('working');
  });

  it('formats a duration', () => {
    expect(formatElapsed(45, t)).toBe(
      'backgroundJobs.card.durationSeconds:{"s":45}',
    );
    expect(formatElapsed(192, t)).toBe(
      'backgroundJobs.card.durationMinutes:{"m":3,"s":12}',
    );
    expect(formatElapsed(3840, t)).toBe(
      'backgroundJobs.card.durationHours:{"h":1,"m":4}',
    );
    expect(formatElapsed(-5, t)).toBe(
      'backgroundJobs.card.durationSeconds:{"s":0}',
    );
  });

  it('counts from the start to the finish, or to now', () => {
    const start = Date.parse('2026-10-06T10:00:00Z');
    expect(
      elapsedSeconds(
        job({ started_at: '2026-10-06T10:00:00Z' }),
        start + 30_000,
      ),
    ).toBe(30);
    expect(
      elapsedSeconds(
        job({
          started_at: '2026-10-06T10:00:00Z',
          finished_at: '2026-10-06T10:01:00Z',
        }),
        start + 999_000,
      ),
    ).toBe(60);
    expect(
      elapsedSeconds(job({ elapsed_s: 10, receivedAt: start }), start + 5_000),
    ).toBe(15);
    expect(elapsedSeconds(undefined, start)).toBeNull();
  });
});

describe('BackgroundJobCard', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    Object.values(service).forEach((fn) => fn.mockReset());
    service.getJob.mockResolvedValue({
      job_id: 'j1',
      conversation_id: 'c1',
      status: 'working',
      started_at: new Date(Date.now() - 65_000).toISOString(),
      auto_resume: true,
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  const makeStore = (health: 'healthy' | 'unhealthy' = 'healthy') =>
    configureStore({
      reducer: {
        background: backgroundReducer,
        notifications: notificationsReducer,
        actionToast: actionToastReducer,
        preference: (state = { token: 'tok' }) => state,
        conversation: (state = { conversationId: 'c1' }) => state,
      },
      preloadedState: {
        notifications: {
          ...notificationsReducer(undefined, { type: 'init' }),
          health,
        },
      },
    });

  const render = async (
    call: ToolCallsType = CALL,
    store = makeStore(),
  ): Promise<ReturnType<typeof makeStore>> => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <BackgroundJobCard toolCall={call} />
        </Provider>,
      );
    });
    return store;
  };

  const button = (label: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === label,
    ) as HTMLButtonElement | undefined;

  it('shows a running job with its elapsed time and a Cancel button', async () => {
    await render();
    expect(service.getJob).toHaveBeenCalledWith('j1', 'tok');
    expect(container.textContent).toContain(
      'backgroundJobs.card.status.working',
    );
    expect(container.textContent).toContain(
      'backgroundJobs.card.durationMinutes',
    );
    expect(container.textContent).toContain('backgroundJobs.card.willResume');
    expect(button('backgroundJobs.card.cancel')).toBeDefined();
  });

  it('says when the result has to be asked for', async () => {
    service.getJob.mockResolvedValue({
      job_id: 'j1',
      status: 'working',
      auto_resume: false,
    });
    await render();
    expect(container.textContent).toContain('backgroundJobs.card.pollOnly');
  });

  it('follows job.updated: progress, then the final state', async () => {
    const store = await render();
    await act(async () => {
      store.dispatch(
        sseEventReceived({
          id: 'e1',
          type: 'job.updated',
          payload: {
            job_id: 'j1',
            status: 'working',
            progress: { percent: 42, last: 'PROGRESS 42%' },
          },
        }),
      );
    });
    expect(container.querySelector('[role="progressbar"]')).not.toBeNull();
    expect(container.textContent).toContain('PROGRESS 42%');

    service.getJob.mockResolvedValue({
      job_id: 'j1',
      status: 'failed',
      started_at: '2026-10-06T10:00:00Z',
      finished_at: '2026-10-06T10:02:00Z',
      error: 'Traceback: boom',
    });
    await act(async () => {
      store.dispatch(
        sseEventReceived({
          id: 'e2',
          type: 'job.updated',
          payload: { job_id: 'j1', status: 'failed' },
        }),
      );
    });
    expect(container.textContent).toContain(
      'backgroundJobs.card.status.failed',
    );
    expect(container.textContent).toContain('Traceback: boom');
    expect(container.textContent).toContain(
      'backgroundJobs.card.durationMinutes',
    );
    expect(button('backgroundJobs.card.cancel')).toBeUndefined();
    expect(container.querySelector('[role="progressbar"]')).toBeNull();
  });

  it('cancels, and shows it is cancelling', async () => {
    service.cancelJob.mockResolvedValue({
      job_id: 'j1',
      status: 'working',
      cancel_requested: true,
    });
    await render();
    await act(async () => button('backgroundJobs.card.cancel')!.click());
    expect(service.cancelJob).toHaveBeenCalledWith('j1', 'tok');
    const cancelling = button('backgroundJobs.card.cancelling');
    expect(cancelling?.disabled).toBe(true);
  });

  it('reports a cancel that failed', async () => {
    service.cancelJob.mockRejectedValue(new Error('HTTP 500'));
    const store = await render();
    await act(async () => button('backgroundJobs.card.cancel')!.click());
    expect(button('backgroundJobs.card.cancel')?.disabled).toBe(false);
    expect(JSON.stringify(store.getState().actionToast)).toContain(
      'backgroundJobs.card.cancelFailed',
    );
  });

  it('a call saved with its outcome needs no fetch', async () => {
    await render({ ...CALL, status: 'completed', job_status: 'completed' });
    expect(service.getJob).not.toHaveBeenCalled();
    expect(container.textContent).toContain(
      'backgroundJobs.card.status.completed',
    );
  });

  it('explains an interrupted job', async () => {
    await render({ ...CALL, status: 'error', job_status: 'lost' });
    expect(container.textContent).toContain('backgroundJobs.card.status.lost');
    expect(container.textContent).toContain('backgroundJobs.card.lostHint');
  });

  it("someone else's job (a shared chat) shows no Cancel and is not polled", async () => {
    vi.useFakeTimers();
    service.getJob.mockRejectedValue(new Error('HTTP 404'));
    await render(CALL, makeStore('unhealthy'));
    expect(button('backgroundJobs.card.cancel')).toBeUndefined();
    await act(async () => {
      vi.advanceTimersByTime(JOB_POLL_MS * 3);
    });
    expect(service.listJobs).not.toHaveBeenCalled();
    expect(service.getJob).toHaveBeenCalledTimes(1);
  });

  it('polls the conversation list only while the stream is down', async () => {
    vi.useFakeTimers();
    service.listJobs.mockResolvedValue([
      { job_id: 'j1', conversation_id: 'c1', status: 'working' },
    ]);
    await render(CALL, makeStore('unhealthy'));
    await act(async () => {
      vi.advanceTimersByTime(JOB_POLL_MS + 10);
    });
    expect(service.listJobs).toHaveBeenCalledWith('c1', 'tok');

    service.listJobs.mockClear();
    await render(CALL, makeStore('healthy'));
    await act(async () => {
      vi.advanceTimersByTime(JOB_POLL_MS * 2);
    });
    expect(service.listJobs).not.toHaveBeenCalled();
  });
});
