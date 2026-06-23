import { describe, expect, it } from 'vitest';

import { sseEventReceived } from '../notifications/notificationsSlice';
import reducer, { clearGraphBuild } from './graphBuildSlice';

const ev = (type: string, id: string, payload: Record<string, unknown>) =>
  sseEventReceived({
    type,
    ts: '',
    user_id: 'u',
    topic: 't',
    scope: { kind: 'source', id },
    payload,
  } as never);

describe('graphBuildSlice', () => {
  it('ignores non-graph events', () => {
    const state = reducer(undefined, ev('source.ingest.progress', 's1', {}));
    expect(state.builds).toEqual({});
  });

  it('tracks building progress keyed by source id', () => {
    const state = reducer(
      undefined,
      ev('graph.extract.progress', 's1', {
        current: 3,
        total: 10,
        nodes: 5,
        edges: 2,
      }),
    );
    expect(state.builds.s1).toEqual({
      status: 'building',
      current: 3,
      total: 10,
      nodes: 5,
      edges: 2,
    });
  });

  it('records a completed summary on the terminal event', () => {
    const state = reducer(
      undefined,
      ev('graph.extract.completed', 's1', {
        nodes: 12,
        edges: 7,
        chunks_processed: 30,
        skipped_over_cap: 2,
        failed_chunks: 1,
      }),
    );
    expect(state.builds.s1.status).toBe('completed');
    expect(state.builds.s1.summary).toEqual({
      nodes: 12,
      edges: 7,
      chunksProcessed: 30,
      skippedOverCap: 2,
      failedChunks: 1,
    });
  });

  it('records a failure with its error', () => {
    const state = reducer(
      undefined,
      ev('graph.extract.failed', 's1', { error: 'boom' }),
    );
    expect(state.builds.s1).toMatchObject({ status: 'failed', error: 'boom' });
  });

  it('does not let a late progress event resurrect a terminal state', () => {
    let state = reducer(
      undefined,
      ev('graph.extract.completed', 's1', { nodes: 1 }),
    );
    state = reducer(
      state,
      ev('graph.extract.progress', 's1', { current: 1, total: 2 }),
    );
    expect(state.builds.s1.status).toBe('completed');
  });

  it('clears an entry on acknowledgement', () => {
    let state = reducer(
      undefined,
      ev('graph.extract.completed', 's1', { nodes: 1 }),
    );
    state = reducer(state, clearGraphBuild('s1'));
    expect(state.builds.s1).toBeUndefined();
  });

  it('drops events without a scope id', () => {
    const state = reducer(
      undefined,
      sseEventReceived({
        type: 'graph.extract.progress',
        ts: '',
        user_id: 'u',
        topic: 't',
        payload: { current: 1, total: 2 },
      } as never),
    );
    expect(state.builds).toEqual({});
  });
});
