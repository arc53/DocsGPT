import type { TFunction } from 'i18next';
import { describe, expect, it } from 'vitest';

import { syncSummary } from './labels';
import type { SyncEvent } from './types';

const source = (id: string, blocked: boolean) => ({
  id,
  name: id,
  type: 'crawler',
  blocked,
  last_synced_at: null,
});

describe('syncSummary', () => {
  it('passes each count to its key formatted', () => {
    const t = ((key: string, opts: { count: number; formatted: string }) =>
      `${key}:${opts.count}/${opts.formatted}`) as unknown as TFunction;
    const event = {
      kind: 'sync',
      sources: [source('a', false), source('b', false), source('c', true)],
    } as unknown as SyncEvent;
    expect(syncSummary(event, t)).toBe(
      'activity.now.syncSources:2/2 · activity.now.syncBlocked:1/1',
    );
  });
});
