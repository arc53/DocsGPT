import { describe, expect, it } from 'vitest';

import type { Doc } from '../../models/misc';
import {
  folderIdOfRow,
  folderPickState,
  folderRowId,
  pickRowIds,
  sourceIncludedBy,
  togglePick,
  type KnowledgePick,
} from './folderPick';
import { buildFolderTree } from './folderTree';
import type { Folder } from './types';

const f = (id: string, parent_id: string | null, name = id): Folder => ({
  id,
  name,
  parent_id,
});
// carriers ─ rates ; customs
const tree = buildFolderTree([
  f('carriers', null, 'Carriers'),
  f('rates', 'carriers', 'Rate archive'),
  f('customs', null, 'Customs & compliance'),
]);
const doc = (id: string, folder_id: string | null = null): Doc =>
  ({ id, name: id, date: '', model: '', folder_id }) as Doc;
const docs = [
  doc('q4', 'carriers'),
  doc('tenders', 'carriers'),
  doc('r2025', 'rates'),
  doc('r2024', 'rates'),
  doc('rules', 'customs'),
  doc('import', 'customs'),
  doc('loose'),
  // Filed in a folder the list doesn't know: counts as in none.
  doc('stray', 'gone'),
];
const pick = (sources: string[] = [], folders: string[] = []) =>
  ({ sources, folders }) as KnowledgePick;

describe('folder row ids', () => {
  it('keeps folder rows apart from source rows', () => {
    expect(folderIdOfRow(folderRowId('carriers'))).toBe('carriers');
    expect(folderIdOfRow('q4')).toBeNull();
    expect(pickRowIds(pick(['q4'], ['customs']))).toEqual([
      'q4',
      'folder:customs',
    ]);
  });
});

describe('folderPickState', () => {
  it('is none with nothing inside picked', () => {
    expect(folderPickState(tree, docs, pick(['loose']), 'customs')).toEqual({
      state: 'none',
      includedBy: null,
      picked: 0,
      total: 2,
    });
  });

  it('is some, counted across the subtree, when a source inside is picked', () => {
    expect(
      folderPickState(tree, docs, pick(['rules']), 'customs'),
    ).toMatchObject({ state: 'some', picked: 1, total: 2 });
    expect(
      folderPickState(tree, docs, pick(['r2024']), 'carriers'),
    ).toMatchObject({ state: 'some', picked: 1, total: 4 });
  });

  it('is some when a subfolder is picked, counting what it brings', () => {
    expect(
      folderPickState(tree, docs, pick([], ['rates']), 'carriers'),
    ).toMatchObject({ state: 'some', picked: 2, total: 4 });
  });

  it('stays some with every source ticked one by one: only a picked folder is live', () => {
    expect(
      folderPickState(tree, docs, pick(['rules', 'import']), 'customs'),
    ).toMatchObject({ state: 'some', picked: 2, total: 2 });
  });

  it('is all when picked, and all with the picked folder above it named', () => {
    expect(
      folderPickState(tree, docs, pick([], ['carriers']), 'carriers'),
    ).toMatchObject({ state: 'all', includedBy: null, picked: 4, total: 4 });
    const inner = folderPickState(tree, docs, pick([], ['carriers']), 'rates');
    expect(inner.state).toBe('all');
    expect(inner.includedBy?.id).toBe('carriers');
  });
});

describe('sourceIncludedBy', () => {
  it('names the picked folder a source comes in with, at any depth', () => {
    const picked = pick([], ['carriers']);
    expect(sourceIncludedBy(tree, docs[2], picked)?.name).toBe('Carriers');
    expect(sourceIncludedBy(tree, docs[4], picked)).toBeNull();
    expect(sourceIncludedBy(tree, docs[7], picked)).toBeNull();
  });
});

describe('togglePick', () => {
  it('toggles a source', () => {
    const on = togglePick(tree, docs, pick(), 'loose');
    expect(on).toEqual(pick(['loose']));
    expect(togglePick(tree, docs, on, 'loose')).toEqual(pick());
  });

  it('toggles a folder as one item', () => {
    const on = togglePick(tree, docs, pick(['loose']), folderRowId('customs'));
    expect(on).toEqual(pick(['loose'], ['customs']));
    expect(togglePick(tree, docs, on, folderRowId('customs'))).toEqual(
      pick(['loose']),
    );
  });

  it('replaces the picks inside a folder when the folder is picked', () => {
    const before = pick(['r2024', 'rules', 'loose'], ['rates']);
    expect(togglePick(tree, docs, before, folderRowId('carriers'))).toEqual(
      pick(['rules', 'loose'], ['carriers']),
    );
  });

  it('leaves a row a picked folder already brings in as it is', () => {
    const picked = pick([], ['carriers']);
    expect(togglePick(tree, docs, picked, 'q4')).toBe(picked);
    expect(togglePick(tree, docs, picked, folderRowId('rates'))).toBe(picked);
  });

  it('takes off a picked folder the list no longer knows', () => {
    expect(
      togglePick(tree, docs, pick([], ['deleted']), folderRowId('deleted')),
    ).toEqual(pick());
  });
});

describe('folderPickState on a mixed tree', () => {
  // ops ─ carriers ─ rates ; ops ─ hubs ; legal ; orphan (parent missing) ;
  // a ⇄ b (a parent loop: both read as top-level)
  const mixed = buildFolderTree([
    f('ops', null, 'Operations'),
    f('carriers', 'ops', 'Carriers'),
    f('rates', 'carriers', 'Rates'),
    f('hubs', 'ops', 'Hubs'),
    f('legal', null, 'Legal'),
    f('orphan', 'missing', 'Orphan'),
    f('a', 'b', 'A'),
    f('b', 'a', 'B'),
  ]);
  const mixedDocs = [
    doc('o1', 'ops'),
    doc('c1', 'carriers'),
    doc('c2', 'carriers'),
    doc('r1', 'rates'),
    doc('r2', 'rates'),
    doc('r3', 'rates'),
    doc('h1', 'hubs'),
    doc('l1', 'legal'),
    doc('or1', 'orphan'),
    doc('a1', 'a'),
    doc('b1', 'b'),
    doc('loose'),
    doc('stray', 'gone'),
  ];
  const ids = [...mixed.byId.keys(), 'deleted'];
  const table = (p: KnowledgePick) =>
    ids.map((id) => {
      const s = folderPickState(mixed, mixedDocs, p, id);
      return `${id}: ${s.state} by=${s.includedBy?.id ?? '-'} ${s.picked}/${s.total}`;
    });

  it('keeps every state, cover and count', () => {
    expect([
      table(pick()),
      table(pick(['r1', 'h1', 'loose', 'stray'])),
      table(pick(['c1'], ['rates'])),
      table(pick(['l1'], ['carriers', 'a', 'deleted'])),
      table(pick(['r2'], ['ops', 'rates'])),
    ]).toMatchInlineSnapshot(`
      [
        [
          "ops: none by=- 0/7",
          "carriers: none by=- 0/5",
          "rates: none by=- 0/3",
          "hubs: none by=- 0/1",
          "legal: none by=- 0/1",
          "orphan: none by=- 0/1",
          "a: none by=- 0/1",
          "b: none by=- 0/1",
          "deleted: none by=- 0/0",
        ],
        [
          "ops: some by=- 2/7",
          "carriers: some by=- 1/5",
          "rates: some by=- 1/3",
          "hubs: some by=- 1/1",
          "legal: none by=- 0/1",
          "orphan: none by=- 0/1",
          "a: none by=- 0/1",
          "b: none by=- 0/1",
          "deleted: none by=- 0/0",
        ],
        [
          "ops: some by=- 4/7",
          "carriers: some by=- 4/5",
          "rates: all by=- 3/3",
          "hubs: none by=- 0/1",
          "legal: none by=- 0/1",
          "orphan: none by=- 0/1",
          "a: none by=- 0/1",
          "b: none by=- 0/1",
          "deleted: none by=- 0/0",
        ],
        [
          "ops: some by=- 5/7",
          "carriers: all by=- 5/5",
          "rates: all by=carriers 3/3",
          "hubs: none by=- 0/1",
          "legal: some by=- 1/1",
          "orphan: none by=- 0/1",
          "a: all by=- 1/1",
          "b: none by=- 0/1",
          "deleted: all by=- 0/0",
        ],
        [
          "ops: all by=- 7/7",
          "carriers: all by=ops 5/5",
          "rates: all by=ops 3/3",
          "hubs: all by=ops 1/1",
          "legal: none by=- 0/1",
          "orphan: none by=- 0/1",
          "a: none by=- 0/1",
          "b: none by=- 0/1",
          "deleted: none by=- 0/0",
        ],
      ]
    `);
  });
});
