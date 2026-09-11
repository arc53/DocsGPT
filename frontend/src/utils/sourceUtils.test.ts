import { describe, expect, it } from 'vitest';

import type { Doc } from '../models/misc';
import {
  selectedSourceIdsFromAgent,
  serializeAgentSources,
  sourceItemId,
  toSourcePickerItems,
} from './sourceUtils';

const doc = (overrides: Partial<Doc>): Doc => ({
  name: 'doc',
  date: '2026-01-01',
  model: 'm',
  ...overrides,
});

const labels = { own: 'Your sources', team: 'Shared with team' };

describe('sourceItemId', () => {
  it('uses the source id when present', () => {
    expect(sourceItemId(doc({ id: 'abc', date: 'd' }))).toBe('abc');
  });

  it('falls back to the date for legacy rows without an id', () => {
    expect(sourceItemId(doc({ date: '2026-02-02' }))).toBe('2026-02-02');
  });
});

describe('toSourcePickerItems', () => {
  it('returns no items for a missing list', () => {
    expect(toSourcePickerItems(null, labels)).toEqual([]);
    expect(toSourcePickerItems(undefined, labels)).toEqual([]);
  });

  it('stays flat when every source is the caller’s own', () => {
    const items = toSourcePickerItems(
      [
        doc({ id: 'a', name: 'A' }),
        doc({ id: 'b', name: 'B', ownership: 'user' }),
      ],
      labels,
      'icon.svg',
    );
    expect(items).toEqual([
      { id: 'a', label: 'A', icon: 'icon.svg' },
      { id: 'b', label: 'B', icon: 'icon.svg' },
    ]);
    expect(items.every((item) => item.group === undefined)).toBe(true);
  });

  it('groups own sources first, then team-shared ones', () => {
    const items = toSourcePickerItems(
      [
        doc({ id: 't1', name: 'Team one', ownership: 'team' }),
        doc({ id: 'o1', name: 'Own one', ownership: 'user' }),
        doc({ id: 't2', name: 'Team two', ownership: 'team' }),
        doc({ id: 'o2', name: 'Own two' }),
      ],
      labels,
    );
    expect(items.map((item) => [item.id, item.group])).toEqual([
      ['o1', 'Your sources'],
      ['o2', 'Your sources'],
      ['t1', 'Shared with team'],
      ['t2', 'Shared with team'],
    ]);
  });
});

describe('serializeAgentSources', () => {
  const docs = [doc({ id: 'a' }), doc({ id: 'b' })];

  it('sends both fields empty when nothing is selected', () => {
    expect(serializeAgentSources([], docs)).toEqual({
      source: '',
      sources: [],
    });
  });

  it('uses the legacy single source field for one selection', () => {
    expect(serializeAgentSources(['a'], docs)).toEqual({
      source: 'a',
      sources: [],
    });
  });

  it('uses the sources list for several selections', () => {
    expect(serializeAgentSources(new Set(['a', 'b']), docs)).toEqual({
      source: '',
      sources: ['a', 'b'],
    });
  });

  it('resolves picker ids to source ids and passes unknown ids through', () => {
    const legacy = doc({ id: undefined, date: 'legacy-date' });
    expect(
      serializeAgentSources(['legacy-date', 'shared-by-owner'], [legacy]),
    ).toEqual({
      source: '',
      sources: ['legacy-date', 'shared-by-owner'],
    });
    expect(serializeAgentSources(['shared-by-owner'], null)).toEqual({
      source: 'shared-by-owner',
      sources: [],
    });
  });

  it('drops duplicates and empty ids', () => {
    expect(serializeAgentSources(['a', 'a', ''], docs)).toEqual({
      source: 'a',
      sources: [],
    });
  });
});

describe('selectedSourceIdsFromAgent', () => {
  it('merges the single source with the sources list', () => {
    expect(
      selectedSourceIdsFromAgent({ source: 'x', sources: ['a', 'b'] }),
    ).toEqual(['x', 'a', 'b']);
  });

  it('keeps a source named in both fields once', () => {
    expect(
      selectedSourceIdsFromAgent({ source: 'a', sources: ['a', 'b'] }),
    ).toEqual(['a', 'b']);
  });

  it('falls back to the single source', () => {
    expect(selectedSourceIdsFromAgent({ source: 'a', sources: [] })).toEqual([
      'a',
    ]);
  });

  it('treats the legacy default placeholder and empty values as no source', () => {
    expect(selectedSourceIdsFromAgent({ source: 'default' })).toEqual([]);
    expect(selectedSourceIdsFromAgent({ sources: ['default', ''] })).toEqual(
      [],
    );
    expect(selectedSourceIdsFromAgent({ source: '' })).toEqual([]);
    expect(selectedSourceIdsFromAgent({})).toEqual([]);
  });

  it('keeps real ids next to a legacy placeholder', () => {
    expect(selectedSourceIdsFromAgent({ sources: ['default', 'a'] })).toEqual([
      'a',
    ]);
  });
});
