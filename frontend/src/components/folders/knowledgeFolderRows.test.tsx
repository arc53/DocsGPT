import type { TFunction } from 'i18next';
import { describe, expect, it, vi } from 'vitest';

import type { Doc } from '../../models/misc';
import { type KnowledgePick, folderRowId } from './folderPick';
import { buildFolderTree } from './folderTree';
import {
  buildKnowledgeRows,
  type KnowledgeRowsInput,
} from './knowledgeFolderRows';
import type { Folder } from './types';

const t = ((key: string, o: Record<string, unknown> = {}) => {
  switch (key) {
    case 'folders.counts.source':
      return `${o.count} sources`;
    case 'folders.counts.folder':
      return `${o.count} folders`;
    case 'folders.counts.empty':
      return 'Empty';
    case 'folders.picker.partial':
      return `${o.picked} of ${o.total} picked`;
    case 'folders.picker.live':
      return `${o.what} · new sources included`;
    case 'folders.picker.includedWith':
      return `Included with ${o.name}`;
    case 'folders.picker.allOf':
      return `All of ${o.name}`;
    case 'folders.picker.inFolder':
      return 'In this folder';
    case 'settings.sources.sections.folders':
      return 'Folders';
    case 'settings.sources.sections.sources':
      return 'Sources';
    case 'conversation.sources.groupTeam':
      return 'Shared with team';
    default:
      return key;
  }
}) as unknown as TFunction;

const f = (
  id: string,
  parent_id: string | null,
  name: string,
  item_count = 0,
  folder_count = 0,
): Folder => ({ id, name, parent_id, item_count, folder_count });
const tree = buildFolderTree([
  f('carriers', null, 'Carriers', 2, 1),
  f('rates', 'carriers', 'Rate archive', 2),
  f('customs', null, 'Customs', 2),
]);
const doc = (
  id: string,
  folder_id: string | null = null,
  ownership?: 'team',
): Doc => ({ id, name: id, date: '', model: '', folder_id, ownership }) as Doc;
const docs = [
  doc('q4', 'carriers'),
  doc('tenders', 'carriers'),
  doc('rates 2025', 'rates'),
  doc('rates 2024', 'rates'),
  doc('rules', 'customs'),
  doc('import', 'customs'),
  doc('loose'),
  doc('graph', null, 'team'),
];

const rows = (overrides: Partial<KnowledgeRowsInput> = {}) =>
  buildKnowledgeRows({
    t,
    tree,
    docs,
    shownDocs: docs,
    pick: { sources: [], folders: [] },
    place: null,
    query: '',
    kindFiltered: false,
    sourceRow: (d, lead) => ({
      id: d.id as string,
      label: d.name,
      description: [lead, 'detail'].filter(Boolean).join(' · '),
    }),
    onOpen: () => undefined,
    ...overrides,
  });
const pick = (
  sources: string[] = [],
  folders: string[] = [],
): KnowledgePick => ({
  sources,
  folders,
});
const summary = (list: ReturnType<typeof rows>) =>
  list.map((row) => [row.group, row.label, row.description]);

describe('buildKnowledgeRows at the root', () => {
  it('lists the top folders, then the loose sources, then the team', () => {
    const list = rows();
    expect(summary(list)).toEqual([
      ['Folders', 'Carriers', '2 sources · 1 folders'],
      ['Folders', 'Customs', '2 sources'],
      ['Sources', 'loose', 'detail'],
      ['Shared with team', 'graph', 'detail'],
    ]);
    expect(list[0].onOpen).toBeTypeOf('function');
    expect(list[2].onOpen).toBeUndefined();
  });

  it('draws a partly picked folder indeterminate with "1 of 2 picked"', () => {
    const [carriers, customs] = rows({ pick: pick(['rules']) });
    expect(customs).toMatchObject({
      checked: 'indeterminate',
      description: '1 of 2 picked',
    });
    expect(carriers.checked).toBeUndefined();
  });

  it('says a picked folder brings its whole subtree, new sources too', () => {
    const [carriers] = rows({ pick: pick([], ['carriers']) });
    expect(carriers.id).toBe(folderRowId('carriers'));
    expect(carriers.description).toBe('4 sources · new sources included');
  });

  it('keeps a picked source or subfolder filed deeper for Selected only, with its trail', () => {
    const list = rows({ pick: pick(['rates 2025'], ['rates']) });
    // rates 2025 sits in a picked folder: it is included, not on its own.
    const pinned = list.filter((row) => row.pinnedOnly);
    expect(pinned.map((row) => [row.label, row.description])).toEqual([
      ['Rate archive', 'Carriers · 2 sources · new sources included'],
      ['rates 2025', 'Included with Rate archive · detail'],
    ]);
  });
});

describe('buildKnowledgeRows in a folder', () => {
  it('leads with All of the folder, then its folders and sources', () => {
    const list = rows({ place: 'carriers' });
    expect(summary(list)).toEqual([
      ['', 'All of Carriers', '4 sources'],
      ['In this folder', 'Rate archive', '2 sources'],
      ['In this folder', 'q4', 'detail'],
      ['In this folder', 'tenders', 'detail'],
    ]);
    expect(list[0].id).toBe(folderRowId('carriers'));
    expect(list[0].onOpen).toBeUndefined();
  });

  it('checks, mutes and fixes everything inside a picked folder', () => {
    const list = rows({ place: 'carriers', pick: pick([], ['carriers']) });
    expect(list[0]).toMatchObject({
      description: '4 sources · new sources included',
      muted: false,
    });
    for (const row of list.slice(1)) {
      expect(row).toMatchObject({ checked: true, muted: true, disabled: true });
      expect(row.description).toMatch(/^Included with Carriers/);
    }
    // A subfolder inside still opens.
    expect(list[1].onOpen).toBeTypeOf('function');
  });

  it('marks All of a folder included when a folder above is picked', () => {
    const [all] = rows({ place: 'rates', pick: pick([], ['carriers']) });
    expect(all).toMatchObject({
      label: 'All of Rate archive',
      description: 'Included with Carriers · 2 sources',
      checked: true,
      muted: true,
      disabled: true,
    });
  });
});

describe('buildKnowledgeRows while searching', () => {
  it('is flat: matching folders first, then sources led by their trail', () => {
    const list = rows({ query: 'RATE' });
    expect(summary(list)).toEqual([
      ['Folders', 'Rate archive', 'Carriers · 2 sources'],
      ['Sources', 'rates 2025', 'Carriers › Rate archive · detail'],
      ['Sources', 'rates 2024', 'Carriers › Rate archive · detail'],
    ]);
    expect(list.every((row) => !row.onOpen)).toBe(true);
  });

  it('matches a source by its folder trail', () => {
    expect(rows({ query: 'customs' }).map((row) => row.label)).toEqual([
      'Customs',
      'rules',
      'import',
    ]);
  });

  it('keeps to the open folder and starts the trail below it', () => {
    const list = rows({
      place: 'carriers',
      query: 'r',
      shownDocs: docs.slice(0, 4),
    });
    expect(summary(list)).toEqual([
      ['Folders', 'Rate archive', '2 sources'],
      ['Sources', 'tenders', 'detail'],
      ['Sources', 'rates 2025', 'Rate archive · detail'],
      ['Sources', 'rates 2024', 'Rate archive · detail'],
    ]);
  });

  it('lists only sources under a kind filter', () => {
    const list = rows({ kindFiltered: true, shownDocs: [docs[0], docs[6]] });
    expect(summary(list)).toEqual([
      ['Sources', 'q4', 'Carriers · detail'],
      ['Sources', 'loose', 'detail'],
    ]);
  });
});

describe('buildKnowledgeRows opening a folder', () => {
  it("calls onOpen with the folder's id", () => {
    const onOpen = vi.fn();
    rows({ onOpen })[0].onOpen?.();
    expect(onOpen).toHaveBeenCalledWith('carriers');
  });

  it('keeps a picked folder the tree lacks, to take it off', () => {
    const list = rows({
      pick: pick([], ['gone']),
      unlistedFolders: [{ id: 'gone', label: 'Deleted folder' }],
    });
    expect(list.find((row) => row.id === folderRowId('gone'))?.label).toBe(
      'Deleted folder',
    );
  });
});

describe('buildKnowledgeRows searching inside a picked folder', () => {
  it('keeps the trail on included rows, so the search still matches it', () => {
    const list = rows({ query: 'rate', pick: pick([], ['carriers']) });
    expect(summary(list)).toEqual([
      ['Folders', 'Rate archive', 'Carriers · 2 sources'],
      ['Sources', 'rates 2025', 'Carriers › Rate archive · detail'],
      ['Sources', 'rates 2024', 'Carriers › Rate archive · detail'],
    ]);
    expect(list.every((row) => row.muted && row.checked === true)).toBe(true);
  });
});
