import { beforeEach, describe, expect, it } from 'vitest';

import notificationsReducer, {
  sseEventReceived,
  type SSEEvent,
} from '../notifications/notificationsSlice';
import reducer, {
  addAttachment,
  addUploadTask,
  dismissUploadTask,
  updateAttachment,
  updateUploadTask,
  type Attachment,
  type UploadTask,
} from './uploadSlice';

const SOURCE_ID = 'src-1';

const makeTask = (overrides: Partial<UploadTask> = {}): UploadTask => ({
  id: 't-1',
  fileName: 'doc.pdf',
  progress: 0,
  status: 'preparing',
  sourceId: SOURCE_ID,
  ...overrides,
});

const stateWithTask = (task: UploadTask) =>
  reducer(undefined, addUploadTask(task));

const ingest = (
  type: string,
  payload: Record<string, unknown> = {},
  scopeId = SOURCE_ID,
) =>
  sseEventReceived({
    id: `id-${type}`,
    type,
    scope: { kind: 'source', id: scopeId },
    payload,
  });

describe('dismissal persistence across reload', () => {
  const STORAGE_KEY = 'docsgpt:dismissedUploadSourceIds';
  const SRC = 'src-persisted';

  // Mirrors initialState as if hydrated from localStorage.
  const seedState = (entries: { id: string; at: number }[]) =>
    reducer(
      { attachments: [], tasks: [], dismissedSourceIds: entries },
      { type: '@@INIT' },
    );

  beforeEach(() => {
    localStorage.clear();
  });

  it('dismissUploadTask writes the task sourceId to localStorage', () => {
    let state = stateWithTask(
      makeTask({ id: 't-dismiss', sourceId: SRC, status: 'completed' }),
    );
    state = reducer(state, dismissUploadTask('t-dismiss'));
    expect(state.tasks[0].dismissed).toBe(true);
    expect(state.dismissedSourceIds).toHaveLength(1);
    expect(state.dismissedSourceIds[0].id).toBe(SRC);
    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]');
    expect(persisted).toHaveLength(1);
    expect(persisted[0].id).toBe(SRC);
  });

  it('skips persistence when the task has no sourceId yet', () => {
    let state = stateWithTask(
      makeTask({ id: 't-no-src', sourceId: undefined, status: 'preparing' }),
    );
    state = reducer(state, dismissUploadTask('t-no-src'));
    expect(state.tasks[0].dismissed).toBe(true);
    expect(state.dismissedSourceIds).toHaveLength(0);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('auto-create on refresh marks the task dismissed when sourceId is in the persisted list', () => {
    const state = seedState([{ id: SRC, at: Date.now() }]);
    const next = reducer(
      state,
      ingest('source.ingest.progress', { current: 40 }, SRC),
    );
    const recovered = next.tasks.find((t) => t.sourceId === SRC);
    expect(recovered).toBeDefined();
    expect(recovered!.dismissed).toBe(true);
    expect(recovered!.progress).toBe(40);
  });

  it('terminal events do NOT un-dismiss a task whose sourceId was previously dismissed', () => {
    const state = seedState([{ id: SRC, at: Date.now() }]);
    let next = reducer(state, ingest('source.ingest.queued', {}, SRC));
    expect(next.tasks[0].dismissed).toBe(true);
    next = reducer(next, ingest('source.ingest.completed', {}, SRC));
    // Even though `wasTerminal` is false (just transitioned), the
    // persisted dismissal keeps the toast closed.
    expect(next.tasks[0].status).toBe('completed');
    expect(next.tasks[0].dismissed).toBe(true);
  });

  it('updateUploadTask does not un-dismiss on terminal when sourceId was previously dismissed', () => {
    const state = reducer(
      {
        attachments: [],
        tasks: [
          makeTask({
            id: 't-1',
            sourceId: SRC,
            status: 'training',
            dismissed: true,
          }),
        ],
        dismissedSourceIds: [{ id: SRC, at: Date.now() }],
      },
      { type: '@@INIT' },
    );
    const next = reducer(
      state,
      updateUploadTask({
        id: 't-1',
        updates: { status: 'completed' },
      }),
    );
    expect(next.tasks[0].status).toBe('completed');
    expect(next.tasks[0].dismissed).toBe(true);
  });

  it('un-dismisses normally for sourceIds NOT in the persisted list', () => {
    const state = reducer(undefined, { type: '@@INIT' });
    const populated = reducer(
      state,
      addUploadTask(
        makeTask({
          id: 't-fresh',
          sourceId: 'src-fresh',
          status: 'training',
          dismissed: true,
        }),
      ),
    );
    const next = reducer(
      populated,
      updateUploadTask({ id: 't-fresh', updates: { status: 'completed' } }),
    );
    expect(next.tasks[0].dismissed).toBe(false);
  });
});

describe('refresh recovery — auto-create from SSE when no task matches', () => {
  it('creates a task on queued for an unknown sourceId', () => {
    let state = reducer(undefined, addUploadTask(makeTask({ id: 'other' })));
    state = reducer(
      state,
      ingest(
        'source.ingest.queued',
        { filename: 'crawler.json', job_name: 'docs' },
        'src-recovery',
      ),
    );
    const recovered = state.tasks.find((t) => t.sourceId === 'src-recovery');
    expect(recovered).toBeDefined();
    expect(recovered!.status).toBe('training');
    expect(recovered!.fileName).toBe('crawler.json');
    expect(recovered!.dismissed).toBe(false);
  });

  it('creates a task on progress for an unknown sourceId and applies the percent', () => {
    let state: ReturnType<typeof reducer> = reducer(undefined, {
      type: '@@INIT',
    });
    state = reducer(
      state,
      ingest(
        'source.ingest.progress',
        { current: 55, total: 10, embedded_chunks: 5 },
        'src-progress',
      ),
    );
    expect(state.tasks).toHaveLength(1);
    expect(state.tasks[0].sourceId).toBe('src-progress');
    expect(state.tasks[0].status).toBe('training');
    expect(state.tasks[0].progress).toBe(55);
  });

  it('does NOT create a task on completed for an unknown sourceId (avoids backlog toast spam)', () => {
    let state: ReturnType<typeof reducer> = reducer(undefined, {
      type: '@@INIT',
    });
    state = reducer(
      state,
      ingest('source.ingest.completed', { tokens: 16 }, 'src-stale'),
    );
    expect(state.tasks).toHaveLength(0);
  });

  it('creates a task on failed for an unknown sourceId so error surfaces post-refresh', () => {
    let state: ReturnType<typeof reducer> = reducer(undefined, {
      type: '@@INIT',
    });
    state = reducer(
      state,
      ingest(
        'source.ingest.failed',
        { error: 'embed worker died' },
        'src-failed',
      ),
    );
    expect(state.tasks).toHaveLength(1);
    expect(state.tasks[0].status).toBe('failed');
    expect(state.tasks[0].errorMessage).toBe('embed worker died');
    expect(state.tasks[0].dismissed).toBe(false);
  });

  it('falls back to job_name then sourceId when filename is absent', () => {
    let state: ReturnType<typeof reducer> = reducer(undefined, {
      type: '@@INIT',
    });
    state = reducer(
      state,
      ingest('source.ingest.queued', { job_name: 'docs-docs' }, 'src-jn'),
    );
    expect(state.tasks[0].fileName).toBe('docs-docs');
    state = reducer(state, ingest('source.ingest.queued', {}, 'src-only'));
    expect(state.tasks.find((t) => t.sourceId === 'src-only')!.fileName).toBe(
      'src-only',
    );
  });

  it('subsequent progress events update the recovered task in place', () => {
    let state: ReturnType<typeof reducer> = reducer(undefined, {
      type: '@@INIT',
    });
    state = reducer(
      state,
      ingest('source.ingest.queued', { filename: 'a.txt' }, 'src-flow'),
    );
    state = reducer(
      state,
      ingest('source.ingest.progress', { current: 30 }, 'src-flow'),
    );
    state = reducer(
      state,
      ingest('source.ingest.progress', { current: 80 }, 'src-flow'),
    );
    state = reducer(
      state,
      ingest('source.ingest.completed', { tokens: 100 }, 'src-flow'),
    );
    expect(state.tasks).toHaveLength(1);
    expect(state.tasks[0].status).toBe('completed');
    expect(state.tasks[0].progress).toBe(100);
  });
});

describe('source.ingest.queued', () => {
  it('does not regress a task already in training', () => {
    let state = stateWithTask(makeTask({ status: 'training', progress: 42 }));
    state = reducer(state, ingest('source.ingest.queued'));
    expect(state.tasks[0].status).toBe('training');
    expect(state.tasks[0].progress).toBe(42);
  });

  it('transitions preparing -> training and zeros progress', () => {
    let state = stateWithTask(makeTask({ status: 'preparing', progress: 12 }));
    state = reducer(state, ingest('source.ingest.queued'));
    expect(state.tasks[0].status).toBe('training');
    expect(state.tasks[0].progress).toBe(0);
  });
});

describe('source.ingest.progress', () => {
  it('clamps to 0..100 and is monotonic', () => {
    let state = stateWithTask(makeTask({ status: 'training' }));
    state = reducer(state, ingest('source.ingest.progress', { current: 30 }));
    expect(state.tasks[0].progress).toBe(30);
    // Higher value advances.
    state = reducer(state, ingest('source.ingest.progress', { current: 150 }));
    expect(state.tasks[0].progress).toBe(100);
    // Lower value never regresses.
    state = reducer(state, ingest('source.ingest.progress', { current: 50 }));
    expect(state.tasks[0].progress).toBe(100);
    // Negative gets clamped at 0 but still cannot regress already-higher.
    state = reducer(state, ingest('source.ingest.progress', { current: -10 }));
    expect(state.tasks[0].progress).toBe(100);
  });
});

describe('source.ingest.completed', () => {
  it('transitions training -> completed and sets dismissed=false', () => {
    let state = stateWithTask(
      makeTask({ status: 'training', dismissed: true }),
    );
    state = reducer(state, ingest('source.ingest.completed'));
    expect(state.tasks[0].status).toBe('completed');
    expect(state.tasks[0].progress).toBe(100);
    expect(state.tasks[0].dismissed).toBe(false);
    expect(state.tasks[0].tokenLimitReached).toBe(false);
  });

  it('with limited=true transitions training -> failed and flags tokenLimitReached', () => {
    let state = stateWithTask(
      makeTask({ status: 'training', dismissed: true }),
    );
    state = reducer(
      state,
      ingest('source.ingest.completed', { limited: true }),
    );
    expect(state.tasks[0].status).toBe('failed');
    expect(state.tasks[0].progress).toBe(100);
    expect(state.tasks[0].tokenLimitReached).toBe(true);
    expect(state.tasks[0].dismissed).toBe(false);
  });

  it('does not re-un-dismiss when a duplicate terminal event arrives', () => {
    // Initial terminal — wasTerminal=false, dismissed flipped to false.
    let state = stateWithTask(makeTask({ status: 'training' }));
    state = reducer(state, ingest('source.ingest.completed'));
    expect(state.tasks[0].dismissed).toBe(false);

    // User dismisses the toast manually.
    state = {
      ...state,
      tasks: state.tasks.map((t) => ({ ...t, dismissed: true })),
    };

    // Duplicate terminal envelope (StrictMode remount, reconnect overlap).
    state = reducer(state, ingest('source.ingest.completed'));
    expect(state.tasks[0].status).toBe('completed');
    expect(state.tasks[0].dismissed).toBe(true);
  });
});

describe('source.ingest.failed', () => {
  it('transitions training -> failed with the error message', () => {
    let state = stateWithTask(makeTask({ status: 'training' }));
    state = reducer(
      state,
      ingest('source.ingest.failed', { error: 'parser blew up' }),
    );
    expect(state.tasks[0].status).toBe('failed');
    expect(state.tasks[0].errorMessage).toBe('parser blew up');
    expect(state.tasks[0].dismissed).toBe(false);
  });

  it('does not re-un-dismiss when a duplicate failed event arrives', () => {
    let state = stateWithTask(makeTask({ status: 'training' }));
    state = reducer(state, ingest('source.ingest.failed', { error: 'oops' }));
    state = {
      ...state,
      tasks: state.tasks.map((t) => ({ ...t, dismissed: true })),
    };
    state = reducer(state, ingest('source.ingest.failed', { error: 'oops' }));
    expect(state.tasks[0].dismissed).toBe(true);
  });
});

describe('attachment race recovery', () => {
  const ATTACHMENT_ID = 'att-1';
  const CLIENT_ID = 'ui-1';

  const attEvent = (
    type: string,
    payload: Record<string, unknown> = {},
  ): SSEEvent => ({
    id: `id-${type}`,
    type,
    scope: { kind: 'attachment', id: ATTACHMENT_ID },
    payload,
  });

  const makeAttachment = (overrides: Partial<Attachment> = {}): Attachment => ({
    id: CLIENT_ID,
    fileName: 'small.pdf',
    progress: 10,
    status: 'processing',
    taskId: 'celery-1',
    attachmentId: ATTACHMENT_ID,
    ...overrides,
  });

  it('drops attachment.completed silently when no row matches attachmentId', () => {
    const state = reducer(
      undefined,
      sseEventReceived(attEvent('attachment.completed', { token_count: 42 })),
    );
    expect(state.attachments).toHaveLength(0);
  });

  it('lands the terminal envelope in notifications.recentEvents for later recovery', () => {
    const notifState = notificationsReducer(
      undefined,
      sseEventReceived(attEvent('attachment.completed', { token_count: 7 })),
    );
    expect(notifState.recentEvents).toHaveLength(1);
    expect(notifState.recentEvents[0].scope?.id).toBe(ATTACHMENT_ID);
    expect(notifState.recentEvents[0].type).toBe('attachment.completed');
  });

  it('reconciler dispatch flips the row to completed after the late row addition', () => {
    // Full race: terminal SSE first, then xhr.onload adds the row,
    // then trackAttachment.check() walks recentEvents and dispatches.
    const terminal = attEvent('attachment.completed', { token_count: 99 });
    const notifState = notificationsReducer(
      undefined,
      sseEventReceived(terminal),
    );

    let uploadState = reducer(undefined, addAttachment(makeAttachment()));
    expect(uploadState.attachments[0].status).toBe('processing');

    const found = notifState.recentEvents.find(
      (e) => e.scope?.id === ATTACHMENT_ID && e.type === 'attachment.completed',
    );
    expect(found).toBeDefined();
    const tokenCount = Number(
      (found?.payload as { token_count?: unknown })?.token_count,
    );
    uploadState = reducer(
      uploadState,
      updateAttachment({
        id: CLIENT_ID,
        updates: {
          status: 'completed',
          progress: 100,
          ...(Number.isFinite(tokenCount) ? { token_count: tokenCount } : {}),
        },
      }),
    );

    expect(uploadState.attachments[0].status).toBe('completed');
    expect(uploadState.attachments[0].progress).toBe(100);
    expect(uploadState.attachments[0].token_count).toBe(99);
  });

  it('attachment.failed envelope can drive a stuck row to failed via reconciler', () => {
    const failed = attEvent('attachment.failed', { error: 'docling boom' });
    const notifState = notificationsReducer(
      undefined,
      sseEventReceived(failed),
    );

    let uploadState = reducer(undefined, addAttachment(makeAttachment()));
    const found = notifState.recentEvents.find(
      (e) => e.scope?.id === ATTACHMENT_ID && e.type === 'attachment.failed',
    );
    expect(found).toBeDefined();

    uploadState = reducer(
      uploadState,
      updateAttachment({ id: CLIENT_ID, updates: { status: 'failed' } }),
    );

    expect(uploadState.attachments[0].status).toBe('failed');
  });
});
