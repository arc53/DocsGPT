import { describe, expect, it } from 'vitest';

import type { Doc } from '../models/misc';
import {
  canSyncSource,
  kindCounts,
  matchesKind,
  sourceKindOf,
  syncNowIsPrimary,
} from './sourceKinds';

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

// The backend's library (tests/api/user/sources/test_workspace_listing.py),
// as the lists send it: the same kinds and counts as `source_kind`.
describe('sourceKindOf', () => {
  const website = { hosts: ['example.com'], pages: 3 } as Doc['website'];
  const library: Record<string, Partial<Doc>> = {
    file: { type: 'local' },
    'file-2': { type: 'local' },
    web: { type: 'website', website },
    // A website on a schedule stays a website.
    'web-scheduled': { type: 'website', website, syncFrequency: 'weekly' },
    synced: { type: 'github', syncFrequency: 'daily' },
    connector: { type: 'connector:google_drive' },
    // A remote loader that never syncs is a file.
    never: { type: 'github', syncFrequency: 'never' },
    // A wiki never syncs, whatever schedule it kept.
    wiki: { type: 'local', config: { kind: 'wiki' }, syncFrequency: 'daily' },
    shared: { type: 'local', ownership: 'team' },
  };

  it('sorts the library as the backend does', () => {
    expect(
      Object.fromEntries(
        Object.entries(library).map(([key, fields]) => [
          key,
          sourceKindOf(doc(fields)),
        ]),
      ),
    ).toEqual({
      file: 'files',
      'file-2': 'files',
      web: 'websites',
      'web-scheduled': 'websites',
      synced: 'synced',
      connector: 'synced',
      never: 'files',
      wiki: 'wikis',
      shared: 'files',
    });
  });

  it.each<[string, Partial<Doc>, string]>([
    ['a wiki by type', { type: 'wiki', connectionId: 'c-1' }, 'wikis'],
    // A website converted to a wiki: the list sends no website summary.
    ['a converted website', { type: 'url', config: { kind: 'wiki' } }, 'wikis'],
    [
      'a source from a connection',
      { type: 's3', connectionId: 'c-1' },
      'synced',
    ],
    // A graph source keeps its content kind.
    [
      'a graph upload',
      { type: 'local', config: { kind: 'graphrag' } },
      'files',
    ],
    [
      'a graph website',
      { type: 'website', website, config: { kind: 'graphrag' } },
      'websites',
    ],
    ['no type at all', {}, 'files'],
  ])('%s', (_, fields, expected) => {
    expect(sourceKindOf(doc(fields))).toBe(expected);
  });

  it('counts each kind; Shared cuts across them', () => {
    const docs = Object.values(library).map((fields) => doc(fields));
    expect(kindCounts(docs)).toEqual({
      all: 9,
      files: 4,
      websites: 2,
      synced: 2,
      wikis: 1,
      shared: 1,
    });
  });

  it('matches a filter: All, a content kind, or Shared of any kind', () => {
    const teamWiki = doc({ type: 'wiki', ownership: 'team' });
    expect(matchesKind('all', teamWiki)).toBe(true);
    expect(matchesKind('wikis', teamWiki)).toBe(true);
    expect(matchesKind('shared', teamWiki)).toBe(true);
    expect(matchesKind('files', teamWiki)).toBe(false);
    expect(matchesKind('shared', doc({ type: 'wiki' }))).toBe(false);
  });
});
