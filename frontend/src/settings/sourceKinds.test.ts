import { describe, expect, it } from 'vitest';

import type { Doc } from '../models/misc';
import { canSyncSource, syncNowIsPrimary } from './sourceKinds';

const doc = (fields: Partial<Doc> = {}): Doc => ({
  id: 'src-1',
  name: 'Contracts',
  date: '',
  model: '',
  ...fields,
});

describe('canSyncSource', () => {
  it.each<[string, Partial<Doc>, boolean]>([
    [
      'a connector source with its connection',
      { type: 'connector:file', connectionId: 'c-1', access: 'owner' },
      true,
    ],
    // The server refuses it (connection_missing): the account was removed.
    [
      "the owner's connector source whose connection is gone",
      { type: 'connector:file', connectionId: null, access: 'owner' },
      false,
    ],
    // A team editor's sync runs with the owner's first connection for the
    // provider, which the editor can't see; the server decides.
    [
      "an editor's connector source (left to the server)",
      { type: 'connector:file', connectionId: null, access: 'editor' },
      true,
    ],
    [
      'a connector source the list says nothing of the connection for',
      { type: 'connector:file', access: 'owner' },
      true,
    ],
    [
      'a scheduled source with no connection',
      { type: 'url', syncFrequency: 'never' },
      true,
    ],
    [
      'a wiki, even with a connection',
      { type: 'wiki', connectionId: 'c-1' },
      false,
    ],
  ])('%s', (_, fields, expected) => {
    expect(canSyncSource(doc(fields))).toBe(expected);
  });
});

describe('syncNowIsPrimary', () => {
  const website = { hosts: ['example.com'], pages: 3 } as Doc['website'];
  it.each<[string, Partial<Doc>, boolean]>([
    [
      'a connector source',
      { type: 'connector:file', connectionId: 'c-1' },
      true,
    ],
    ['a scheduled source', { type: 's3', syncFrequency: 'daily' }, true],
    ['an upload', { type: 'local', isNested: true }, false],
    // A website keeps Add pages; its Sync now is in the ⋯.
    ['a synced website', { syncFrequency: 'daily', website }, false],
    // Its Files tab keeps its own action.
    [
      'a synced graph source',
      { connectionId: 'c-1', config: { kind: 'graphrag' } },
      false,
    ],
    ['a wiki', { type: 'wiki', connectionId: 'c-1' }, false],
  ])('%s', (_, fields, expected) => {
    expect(syncNowIsPrimary(doc(fields))).toBe(expected);
  });
});
