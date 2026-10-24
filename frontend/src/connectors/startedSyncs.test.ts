import { describe, expect, it } from 'vitest';

import type { SSEEvent } from '../notifications/notificationsSlice';
import { partitionStartedSyncs, syncIdsKey } from './startedSyncs';

const sync = (id: string) => ({
  id,
  name: id,
  connectionId: 'c-1',
  startedAt: '2026-10-24T10:00:00Z',
});
const event = (id: string, type: string) =>
  ({ type, scope: { id } }) as unknown as SSEEvent;

describe('partitionStartedSyncs', () => {
  const started = ['a', 'b', 'c', 'd', 'e'].map(sync);
  const events = [
    event('b', 'source.ingest.completed'),
    event('c', 'source.ingest.failed'),
    event('d', 'source.ingest.completed'),
    event('e', 'source.ingest.failed'),
  ];
  // d and e are listed: d finished (a source synced again), e failed.
  const { unlisted, listedFinished } = partitionStartedSyncs(
    started,
    (id) => id === 'd' || id === 'e',
    events,
  );

  it('keeps the unlisted syncs in start order, each with its state', () => {
    expect(unlisted.map(({ id, state }) => [id, state])).toEqual([
      ['a', null],
      ['b', 'completed'],
      ['c', 'failed'],
    ]);
  });

  it('names only the listed syncs that finished', () => {
    expect(listedFinished).toEqual(['d']);
  });

  it.each([
    [null, 'a'],
    ['completed', 'b'],
    ['failed', 'c'],
  ] as const)('keys the %s syncs by their ids', (state, key) => {
    expect(syncIdsKey(unlisted, state)).toBe(key);
  });
});
