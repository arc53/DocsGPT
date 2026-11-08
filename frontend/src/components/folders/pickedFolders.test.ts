import type { TFunction } from 'i18next';
import { describe, expect, it } from 'vitest';

import type { Doc } from '../../models/misc';
import { buildFolderTree } from './folderTree';
import {
  pickedFolders,
  pickedFoldersHint,
  stoppedFolderLines,
  unlistedFolderRow,
} from './pickedFolders';

const t = ((key: string, o: Record<string, unknown> = {}) =>
  `${key}${JSON.stringify(
    Object.fromEntries(
      Object.entries(o).filter(([k]) => k !== 'interpolation'),
    ),
  )}`) as unknown as TFunction;

const tree = buildFolderTree([
  { id: 'carriers', name: 'Carriers', parent_id: null },
  { id: 'rates', name: 'Rate archive', parent_id: 'carriers' },
  { id: 'customs', name: 'Customs', parent_id: null },
]);
const doc = (id: string, folder_id: string | null): Doc =>
  ({ id, name: id, date: '', model: '', folder_id }) as Doc;
const docs = [
  doc('a', 'carriers'),
  doc('b', 'rates'),
  doc('c', 'rates'),
  doc('d', 'customs'),
  doc('e', null),
];

describe('pickedFolders', () => {
  it('names and counts own folders live, subfolders included', () => {
    expect(pickedFolders(tree, docs, ['carriers', 'customs'])).toEqual([
      { id: 'carriers', name: 'Carriers', sourceCount: 3 },
      { id: 'customs', name: 'Customs', sourceCount: 1 },
    ]);
  });

  it("reads a teammate's or a deleted folder from the server's details", () => {
    const list = pickedFolders(
      tree,
      docs,
      ['lena', 'gone', 'stopped'],
      [
        {
          id: 'lena',
          name: 'Lena docs',
          source_count: 4,
          owner_name: 'lena@x.io',
        },
        { id: 'gone', name: null, stopped: true, reason: 'deleted' },
        {
          id: 'stopped',
          name: 'Ops',
          source_count: 0,
          owner_name: 'dan@x.io',
          stopped: true,
          reason: 'sponsor_cannot_edit_agent',
        },
      ],
    );
    expect(list).toEqual([
      {
        id: 'lena',
        name: 'Lena docs',
        sourceCount: 4,
        ownerName: 'lena@x.io',
        stopped: undefined,
      },
      {
        id: 'gone',
        name: null,
        sourceCount: 0,
        ownerName: undefined,
        stopped: 'deleted',
      },
      {
        id: 'stopped',
        name: 'Ops',
        sourceCount: 0,
        ownerName: 'dan@x.io',
        stopped: 'sponsor_cannot_edit_agent',
      },
    ]);
  });
});

describe('pickedFoldersHint', () => {
  it('names one folder and what it brings', () => {
    expect(pickedFoldersHint(t, pickedFolders(tree, docs, ['carriers']))).toBe(
      'folders.picker.hintOne{"count":3,"formatted":"3","name":"Carriers"}',
    );
  });

  it('names several folders with one total, and skips stopped ones', () => {
    const list = [
      ...pickedFolders(tree, docs, ['carriers', 'customs']),
      { id: 'x', name: 'Ops', sourceCount: 9, stopped: 'deleted' as const },
    ];
    expect(pickedFoldersHint(t, list, 'en')).toBe(
      'folders.picker.hintMany{"count":4,"formatted":"4","names":"Carriers and Customs"}',
    );
    expect(pickedFoldersHint(t, [])).toBeNull();
  });
});

describe('stoppedFolderLines and unlistedFolderRow', () => {
  const stopped = {
    id: 's',
    name: 'Ops',
    sourceCount: 0,
    ownerName: 'dan@x.io',
    stopped: 'sponsor_cannot_edit_agent' as const,
  };
  const deleted = {
    id: 'g',
    name: null,
    sourceCount: 0,
    stopped: 'deleted' as const,
  };

  it('says why each folder stopped', () => {
    expect(stoppedFolderLines(t, [stopped, deleted])).toEqual([
      'folders.picker.stopped{"name":"Ops","person":"dan@x.io"}',
      'folders.picker.deleted{"count":1,"formatted":"1"}',
    ]);
  });

  it('labels the remove-only rows', () => {
    expect(unlistedFolderRow(t, deleted)).toEqual({
      label: 'folders.picker.deletedFolder{}',
      line: 'folders.picker.deletedLine{}',
    });
    expect(unlistedFolderRow(t, stopped)).toEqual({
      label: 'Ops',
      line: 'folders.picker.ownersFolder{"person":"dan@x.io"} · folders.picker.stoppedShort{}',
    });
  });
});
