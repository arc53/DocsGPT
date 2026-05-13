import { describe, expect, it } from 'vitest';

import { sseEventReceived } from '../notifications/notificationsSlice';
import reducer, { addUploadTask, type UploadTask } from './uploadSlice';

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
