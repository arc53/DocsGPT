import { beforeEach, describe, expect, it, vi } from 'vitest';

import notificationsReducer, {
  sseEventReceived,
  type SSEEvent,
} from '../notifications/notificationsSlice';
import type { RootState } from '../store';
import reducer, {
  addAttachment,
  addUploadTask,
  dismissUploadTask,
  EARLY_ATTACHMENT_EVENTS_CAP,
  EARLY_ATTACHMENT_EVENTS_TTL_MS,
  selectSendableAttachmentIds,
  selectSendableAttachments,
  toSendableAttachments,
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
      {
        attachments: [],
        tasks: [],
        dismissedSourceIds: entries,
        earlyAttachmentEvents: {},
      },
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
        earlyAttachmentEvents: {},
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

  it('records the ingest stage from the payload', () => {
    let state = stateWithTask(makeTask({ status: 'training' }));
    state = reducer(
      state,
      ingest('source.ingest.progress', { current: 20, stage: 'parsing' }),
    );
    expect(state.tasks[0].stage).toBe('parsing');
    state = reducer(
      state,
      ingest('source.ingest.progress', { current: 70, stage: 'embedding' }),
    );
    expect(state.tasks[0].stage).toBe('embedding');
    // An unknown/absent stage leaves the last known value intact.
    state = reducer(
      state,
      ingest('source.ingest.progress', { current: 80, stage: 'bogus' }),
    );
    expect(state.tasks[0].stage).toBe('embedding');
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

  it('keeps the mime type and extraction status a completed attachment reports', () => {
    let state = reducer(undefined, addAttachment(makeAttachment()));
    state = reducer(
      state,
      sseEventReceived(
        attEvent('attachment.completed', {
          token_count: 0,
          mime_type: 'application/pdf',
          extraction_status: 'no_text',
        }),
      ),
    );

    expect(state.attachments[0].status).toBe('completed');
    expect(state.attachments[0].mimeType).toBe('application/pdf');
    expect(state.attachments[0].extractionStatus).toBe('no_text');
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
    // The send paths read ``id``: it must be the server's, not the
    // client placeholder, or the backend silently drops the file.
    expect(uploadState.attachments[0].id).toBe(ATTACHMENT_ID);
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

describe('upload race — SSE auto-created duplicate absorbed on sourceId bind', () => {
  it('merges the orphan row when the upload response binds the sourceId', () => {
    // Client row exists without a sourceId (upload XHR still in flight)...
    let state = stateWithTask(
      makeTask({
        id: 'client-1',
        sourceId: undefined,
        status: 'uploading',
        fileName: 'doc4.pdf',
      }),
    );
    // ...and the worker's queued event lands first — the slice cannot
    // match it, so it auto-creates an orphan row keyed by sourceId.
    state = reducer(
      state,
      ingest('source.ingest.queued', { filename: 'doc4.pdf' }),
    );
    expect(state.tasks).toHaveLength(2);

    // The XHR response now binds the sourceId to the client row: the
    // orphan must be absorbed, not left behind as a stuck duplicate.
    state = reducer(
      state,
      updateUploadTask({
        id: 'client-1',
        updates: {
          taskId: 'task-9',
          sourceId: SOURCE_ID,
          status: 'training',
          progress: 0,
        },
      }),
    );

    expect(state.tasks).toHaveLength(1);
    expect(state.tasks[0].id).toBe('client-1');
    expect(state.tasks[0].sourceId).toBe(SOURCE_ID);
  });

  it('keeps the orphan progress and terminal state when it advanced further', () => {
    let state = stateWithTask(
      makeTask({ id: 'client-1', sourceId: undefined, status: 'uploading' }),
    );
    state = reducer(
      state,
      ingest('source.ingest.queued', { filename: 'doc.pdf' }),
    );
    state = reducer(
      state,
      ingest('source.ingest.progress', { current: 80, stage: 'embedding' }),
    );
    state = reducer(state, ingest('source.ingest.completed', {}));

    state = reducer(
      state,
      updateUploadTask({
        id: 'client-1',
        updates: { sourceId: SOURCE_ID, status: 'training', progress: 0 },
      }),
    );

    expect(state.tasks).toHaveLength(1);
    const task = state.tasks[0];
    expect(task.id).toBe('client-1');
    expect(task.status).toBe('completed');
    expect(task.progress).toBe(100);
  });
});

describe('server id binding on completion', () => {
  const row = (overrides: Partial<Attachment> = {}): Attachment => ({
    id: 'ui-1',
    fileName: 'a.pdf',
    progress: 10,
    status: 'processing',
    taskId: 'celery-1',
    attachmentId: 'srv-1',
    ...overrides,
  });

  it('swaps in the server id when an update completes a bound row', () => {
    let state = reducer(undefined, addAttachment(row()));
    state = reducer(
      state,
      updateAttachment({ id: 'ui-1', updates: { status: 'completed' } }),
    );
    expect(state.attachments[0].id).toBe('srv-1');
  });

  it('binds the id when the same update sets attachmentId and completes', () => {
    let state = reducer(
      undefined,
      addAttachment(row({ attachmentId: undefined, status: 'uploading' })),
    );
    state = reducer(
      state,
      updateAttachment({
        id: 'ui-1',
        updates: { attachmentId: 'srv-2', status: 'completed' },
      }),
    );
    expect(state.attachments[0].id).toBe('srv-2');
  });

  it('keeps the client id while the row is still processing', () => {
    let state = reducer(undefined, addAttachment(row()));
    state = reducer(
      state,
      updateAttachment({ id: 'ui-1', updates: { progress: 50 } }),
    );
    expect(state.attachments[0].id).toBe('ui-1');
  });
});

describe('sendable attachments', () => {
  const att = (overrides: Partial<Attachment>): Attachment => ({
    id: 'ui-1',
    fileName: 'a.pdf',
    progress: 100,
    status: 'completed',
    taskId: 't',
    ...overrides,
  });

  it('sends the server id of completed rows only', () => {
    const rows = [
      att({ id: 'ui-1', attachmentId: 'srv-1', fileName: 'a.pdf' }),
      att({ id: 'ui-2', attachmentId: 'srv-2', status: 'processing' }),
      att({ id: 'ui-3', attachmentId: 'srv-3', status: 'failed' }),
      att({ id: 'srv-4', attachmentId: 'srv-4', fileName: 'd.pdf' }),
    ];
    expect(toSendableAttachments(rows)).toEqual([
      { id: 'srv-1', fileName: 'a.pdf' },
      { id: 'srv-4', fileName: 'd.pdf' },
    ]);
  });

  it('falls back to id for rows without an attachmentId', () => {
    expect(toSendableAttachments([att({ id: 'legacy' })])).toEqual([
      { id: 'legacy', fileName: 'a.pdf' },
    ]);
  });

  it('drops empty ids and sends a repeated server id once', () => {
    const rows = [
      att({ id: '' }),
      att({ id: 'ui-1', attachmentId: 'same' }),
      att({ id: 'ui-2', attachmentId: 'same', fileName: 'copy.pdf' }),
    ];
    expect(toSendableAttachments(rows).map((a) => a.id)).toEqual(['same']);
  });

  it('exposes the same view through the store selectors', () => {
    const upload = reducer(
      undefined,
      addAttachment(att({ id: 'ui-1', attachmentId: 'srv-1' })),
    );
    const state = { upload } as unknown as RootState;
    expect(selectSendableAttachments(state)).toEqual([
      { id: 'srv-1', fileName: 'a.pdf' },
    ]);
    expect(selectSendableAttachmentIds(state)).toEqual(['srv-1']);
  });
});

describe('attachment events that arrive before the upload response', () => {
  const attEvent = (
    type: string,
    attachmentId: string,
    payload: Record<string, unknown> = {},
  ): SSEEvent => ({
    id: `${attachmentId}-${type}-${JSON.stringify(payload)}`,
    type,
    scope: { kind: 'attachment', id: attachmentId },
    payload,
  });

  const uploading = (id: string): Attachment => ({
    id,
    fileName: `${id}.pdf`,
    progress: 40,
    status: 'uploading',
    taskId: '',
  });

  const bind = (id: string, attachmentId: string) =>
    updateAttachment({
      id,
      updates: {
        taskId: `celery-${id}`,
        attachmentId,
        status: 'processing',
        progress: 10,
      },
    });

  it('applies a stashed completion when the row learns its attachment id', () => {
    let state = reducer(undefined, addAttachment(uploading('ui-1')));
    state = reducer(
      state,
      sseEventReceived(
        attEvent('attachment.completed', 'srv-1', {
          token_count: 5,
          mime_type: 'application/pdf',
        }),
      ),
    );
    expect(state.attachments[0].status).toBe('uploading');

    state = reducer(state, bind('ui-1', 'srv-1'));

    const [row] = state.attachments;
    expect(row.status).toBe('completed');
    expect(row.progress).toBe(100);
    expect(row.id).toBe('srv-1');
    expect(row.token_count).toBe(5);
    expect(row.mimeType).toBe('application/pdf');
  });

  it('applies a stashed failure', () => {
    let state = reducer(undefined, addAttachment(uploading('ui-1')));
    state = reducer(
      state,
      sseEventReceived(attEvent('attachment.failed', 'srv-1')),
    );
    state = reducer(state, bind('ui-1', 'srv-1'));
    expect(state.attachments[0].status).toBe('failed');
  });

  it("keeps the worker's reason on a failed row", () => {
    let state = reducer(undefined, addAttachment(uploading('ui-1')));
    state = reducer(state, bind('ui-1', 'srv-1'));
    state = reducer(
      state,
      sseEventReceived(
        attEvent('attachment.failed', 'srv-1', {
          error: 'File is password protected',
        }),
      ),
    );
    expect(state.attachments[0].status).toBe('failed');
    expect(state.attachments[0].errorMessage).toBe(
      'File is password protected',
    );
  });

  it('leaves a failed row without a reason when the worker gave none', () => {
    let state = reducer(undefined, addAttachment(uploading('ui-1')));
    state = reducer(state, bind('ui-1', 'srv-1'));
    state = reducer(
      state,
      sseEventReceived(attEvent('attachment.failed', 'srv-1', { error: ' ' })),
    );
    expect(state.attachments[0].status).toBe('failed');
    expect(state.attachments[0].errorMessage).toBeUndefined();
  });

  it('keeps progress from stashed events without completing the row', () => {
    let state = reducer(undefined, addAttachment(uploading('ui-1')));
    state = reducer(
      state,
      sseEventReceived(
        attEvent('attachment.progress', 'srv-1', { current: 60 }),
      ),
    );
    state = reducer(state, bind('ui-1', 'srv-1'));
    expect(state.attachments[0].status).toBe('processing');
    expect(state.attachments[0].progress).toBe(60);
    expect(state.attachments[0].id).toBe('ui-1');
  });

  it('completes every row of a batch larger than the notifications ring', () => {
    const count = 40;
    let state = reducer(undefined, { type: '@@INIT' });
    let notifications = notificationsReducer(undefined, { type: '@@INIT' });
    for (let i = 0; i < count; i++) {
      state = reducer(state, addAttachment(uploading(`ui-${i}`)));
    }
    // The worker finishes every file before any upload response lands:
    // queued, two progress ticks and a completion per file.
    for (let i = 0; i < count; i++) {
      for (const event of [
        attEvent('attachment.queued', `srv-${i}`),
        attEvent('attachment.progress', `srv-${i}`, { current: 30 }),
        attEvent('attachment.progress', `srv-${i}`, { current: 80 }),
        attEvent('attachment.completed', `srv-${i}`, { token_count: i }),
      ]) {
        const action = sseEventReceived(event);
        state = reducer(state, action);
        notifications = notificationsReducer(notifications, action);
      }
    }
    // The early completions are gone from the ring buffer...
    expect(
      notifications.recentEvents.some((e) => e.scope?.id === 'srv-0'),
    ).toBe(false);

    for (let i = 0; i < count; i++) {
      state = reducer(state, bind(`ui-${i}`, `srv-${i}`));
    }
    // ...but every row still completes, under its server id.
    expect(state.attachments.every((a) => a.status === 'completed')).toBe(true);
    expect(state.attachments.map((a) => a.id)).toEqual(
      Array.from({ length: count }, (_, i) => `srv-${i}`),
    );
  });

  it('does not stash events while no upload is waiting for its id', () => {
    // A page load replays the SSE backlog: none of it is ours to keep.
    let state = reducer(undefined, { type: '@@INIT' });
    state = reducer(
      state,
      sseEventReceived(attEvent('attachment.completed', 'srv-old')),
    );
    expect(Object.keys(state.earlyAttachmentEvents)).toHaveLength(0);
  });

  it('drops stashed events once their row is bound', () => {
    let state = reducer(undefined, addAttachment(uploading('ui-1')));
    state = reducer(
      state,
      sseEventReceived(attEvent('attachment.completed', 'srv-1')),
    );
    expect(Object.keys(state.earlyAttachmentEvents)).toEqual(['srv-1']);
    state = reducer(state, bind('ui-1', 'srv-1'));
    expect(Object.keys(state.earlyAttachmentEvents)).toHaveLength(0);
  });

  it('keeps the stash bounded', () => {
    let state = reducer(undefined, addAttachment(uploading('ui-1')));
    for (let i = 0; i < EARLY_ATTACHMENT_EVENTS_CAP + 50; i++) {
      state = reducer(
        state,
        sseEventReceived(attEvent('attachment.completed', `stray-${i}`)),
      );
    }
    expect(Object.keys(state.earlyAttachmentEvents)).toHaveLength(
      EARLY_ATTACHMENT_EVENTS_CAP,
    );
    // The oldest go first.
    expect(state.earlyAttachmentEvents['stray-0']).toBeUndefined();
  });

  it('forgets stashed events after the TTL', () => {
    vi.useFakeTimers();
    try {
      let state = reducer(undefined, addAttachment(uploading('ui-1')));
      state = reducer(
        state,
        sseEventReceived(attEvent('attachment.completed', 'srv-1')),
      );
      vi.advanceTimersByTime(EARLY_ATTACHMENT_EVENTS_TTL_MS + 1);
      state = reducer(state, bind('ui-1', 'srv-1'));
      expect(state.attachments[0].status).toBe('processing');
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('processing activity', () => {
  const event = (
    type: string,
    attachmentId: string,
    payload: Record<string, unknown>,
    n: number,
  ): SSEEvent => ({
    id: `${attachmentId}-${n}`,
    type,
    scope: { kind: 'attachment', id: attachmentId },
    payload,
  });

  const processing: Attachment = {
    id: 'ui-1',
    fileName: 'bundle.zip',
    progress: 10,
    status: 'processing',
    taskId: 'celery-1',
    attachmentId: 'srv-1',
  };

  it('counts every queued or progress event, even one that does not move the bar', () => {
    let state = reducer(undefined, addAttachment(processing));
    const before = state.attachments[0].activity ?? 0;
    state = reducer(
      state,
      sseEventReceived(event('attachment.queued', 'srv-1', {}, 1)),
    );
    state = reducer(
      state,
      sseEventReceived(
        event('attachment.progress', 'srv-1', { current: 40 }, 2),
      ),
    );
    state = reducer(
      state,
      sseEventReceived(
        event('attachment.progress', 'srv-1', { current: 40 }, 3),
      ),
    );
    expect(state.attachments[0].progress).toBe(40);
    expect(state.attachments[0].activity).toBe(before + 3);
  });

  it('counts progress replayed when the row learns its id', () => {
    let state = reducer(
      undefined,
      addAttachment({
        ...processing,
        status: 'uploading',
        attachmentId: undefined,
      }),
    );
    state = reducer(
      state,
      sseEventReceived(
        event('attachment.progress', 'srv-1', { current: 30 }, 1),
      ),
    );
    expect(state.attachments[0].activity ?? 0).toBe(0);
    state = reducer(
      state,
      updateAttachment({
        id: 'ui-1',
        updates: { attachmentId: 'srv-1', status: 'processing' },
      }),
    );
    expect(state.attachments[0].activity).toBe(1);
  });
});
