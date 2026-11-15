import { describe, expect, it } from 'vitest';

import {
  buildFolderTree,
  canCreateIn,
  childFolders,
  folderDepth,
  folderMoveCheck,
  folderPagePath,
  folderPath,
  folderShowsOn,
  formatFolderPath,
  matchingFolders,
  searchParentName,
  subtreeHeight,
  subtreeIds,
} from './folderTree';
import type { Folder } from './types';

const f = (id: string, parent_id: string | null, name = id): Folder => ({
  id,
  name,
  parent_id,
});

// carriers ─ rates ─ archive ; customs ; product
const folders = [
  f('archive', 'rates', 'Archive'),
  f('carriers', null, 'Carriers'),
  f('rates', 'carriers', 'Rate archive'),
  f('product', null, 'product docs'),
  f('customs', null, 'Customs'),
];

describe('buildFolderTree', () => {
  it('lists children by name, case-insensitively', () => {
    const tree = buildFolderTree(folders);
    expect(childFolders(tree, null).map((x) => x.id)).toEqual([
      'carriers',
      'customs',
      'product',
    ]);
    expect(childFolders(tree, 'carriers').map((x) => x.id)).toEqual(['rates']);
  });

  it('puts a folder whose parent is missing at the top level', () => {
    const tree = buildFolderTree([f('orphan', 'gone')]);
    expect(childFolders(tree, null).map((x) => x.id)).toEqual(['orphan']);
    expect(folderPath(tree, 'orphan').map((x) => x.id)).toEqual(['orphan']);
  });

  it('survives a parent loop', () => {
    const tree = buildFolderTree([f('a', 'b'), f('b', 'a'), f('c', 'a')]);
    // Both loop members surface at the top level; nothing hangs.
    expect(childFolders(tree, null).map((x) => x.id)).toEqual(['a', 'b']);
    expect(folderPath(tree, 'c').map((x) => x.id)).toEqual(['a', 'c']);
    expect([...subtreeIds(tree, 'a')].sort()).toEqual(['a', 'c']);
    expect(subtreeHeight(tree, 'a')).toBe(2);
  });
});

describe('paths and depth', () => {
  const tree = buildFolderTree(folders);

  it('gives the trail top level first', () => {
    expect(folderPath(tree, 'archive').map((x) => x.id)).toEqual([
      'carriers',
      'rates',
      'archive',
    ]);
    expect(formatFolderPath(folderPath(tree, 'archive'))).toBe(
      'Carriers › Rate archive › Archive',
    );
    expect(folderPath(tree, 'nope')).toEqual([]);
    expect(folderPath(tree, null)).toEqual([]);
  });

  it('counts depth from the top level', () => {
    expect(folderDepth(tree, null)).toBe(0);
    expect(folderDepth(tree, 'carriers')).toBe(1);
    expect(folderDepth(tree, 'archive')).toBe(3);
  });

  it('measures a subtree', () => {
    expect([...subtreeIds(tree, 'carriers')].sort()).toEqual([
      'archive',
      'carriers',
      'rates',
    ]);
    expect(subtreeHeight(tree, 'carriers')).toBe(3);
    expect(subtreeHeight(tree, 'customs')).toBe(1);
  });

  it('stops new folders at the third level', () => {
    expect(canCreateIn(tree, null)).toBe(true);
    expect(canCreateIn(tree, 'rates')).toBe(true);
    expect(canCreateIn(tree, 'archive')).toBe(false);
  });
});

describe('folderMoveCheck', () => {
  const tree = buildFolderTree(folders);

  it('knows where a folder already is', () => {
    expect(folderMoveCheck(tree, 'rates', 'carriers')).toBe('same');
    expect(folderMoveCheck(tree, 'customs', null)).toBe('same');
  });

  it('refuses a move into itself or below', () => {
    expect(folderMoveCheck(tree, 'carriers', 'carriers')).toBe('cycle');
    expect(folderMoveCheck(tree, 'carriers', 'archive')).toBe('cycle');
  });

  it('refuses a move that would nest past three levels', () => {
    // carriers spans 3 levels: only the top level fits it.
    expect(folderMoveCheck(tree, 'carriers', 'customs')).toBe('too_deep');
    expect(folderMoveCheck(tree, 'customs', 'rates')).toBe('ok');
    expect(folderMoveCheck(tree, 'customs', 'archive')).toBe('too_deep');
    expect(folderMoveCheck(tree, 'archive', null)).toBe('ok');
  });
});

describe('matchingFolders', () => {
  const tree = buildFolderTree(folders);

  it('finds folders by name at any depth, by trail', () => {
    expect(matchingFolders(tree, ' ARCH ').map((x) => x.id)).toEqual([
      'rates',
      'archive',
    ]);
    expect(matchingFolders(tree, '')).toEqual([]);
  });

  it('keeps to a subtree when given one', () => {
    const within = subtreeIds(tree, 'rates');
    within.delete('rates');
    expect(matchingFolders(tree, 'arch', within).map((x) => x.id)).toEqual([
      'archive',
    ]);
  });
});

describe('searchParentName', () => {
  const tree = buildFolderTree(folders);

  it('names the parent of a nested folder found by a search', () => {
    expect(searchParentName(tree, tree.byId.get('rates')!, null)).toBe(
      'Carriers',
    );
  });

  it('names none at the top level or right in the open folder', () => {
    expect(searchParentName(tree, tree.byId.get('carriers')!, null)).toBe(
      undefined,
    );
    expect(
      searchParentName(tree, tree.byId.get('rates')!, 'carriers'),
    ).toBeUndefined();
  });
});

describe('folderShowsOn', () => {
  const counted = (
    id: string,
    parent_id: string | null,
    counts: Partial<Record<'agent' | 'source' | 'tool' | 'prompt', number>>,
  ): Folder => ({
    id,
    name: id,
    parent_id,
    counts: { agent: 0, source: 0, tool: 0, prompt: 0, ...counts },
  });
  // onboarding (2 prompts) ─ forms (1 agent) ; agents (3 agents) ─ deep (1
  // prompt) ; empty ─ inner (empty) ; mixed (1 tool) ─ inner2 (empty)
  const tree = buildFolderTree([
    counted('onboarding', null, { prompt: 2 }),
    counted('forms', 'onboarding', { agent: 1 }),
    counted('agents', null, { agent: 3 }),
    counted('deep', 'agents', { prompt: 1 }),
    counted('empty', null, {}),
    counted('inner', 'empty', {}),
    counted('mixed', null, { tool: 1 }),
    counted('inner2', 'mixed', {}),
  ]);
  const shows = (id: string, kind: 'agent' | 'source' | 'tool' | 'prompt') =>
    folderShowsOn(tree, tree.byId.get(id)!, kind);

  it('shows a folder whose subtree holds the kind', () => {
    expect(shows('onboarding', 'prompt')).toBe(true);
    // Its prompt sits a level down.
    expect(shows('agents', 'prompt')).toBe(true);
    expect(shows('onboarding', 'agent')).toBe(true);
  });

  it('shows a folder with nothing in its subtree on every page', () => {
    for (const kind of ['agent', 'source', 'tool', 'prompt'] as const) {
      expect(shows('empty', kind)).toBe(true);
      expect(shows('inner', kind)).toBe(true);
    }
  });

  it('hides a folder that holds only other kinds', () => {
    expect(shows('forms', 'prompt')).toBe(false);
    expect(shows('mixed', 'agent')).toBe(false);
    expect(shows('onboarding', 'source')).toBe(false);
    // An empty folder inside one still shows: there is nothing in it.
    expect(shows('inner2', 'agent')).toBe(true);
  });

  it('shows a folder whose counts the server did not send', () => {
    const old = buildFolderTree([f('legacy', null)]);
    expect(folderShowsOn(old, old.byId.get('legacy')!, 'tool')).toBe(true);
  });
});

describe('folderPagePath', () => {
  it("opens the folder on each kind's page", () => {
    expect(folderPagePath('agent', 'f 1')).toBe('/agents?folder=f%201');
    expect(folderPagePath('source', 'f1')).toBe(
      '/settings/knowledge?folder=f1',
    );
    expect(folderPagePath('tool', 'f1')).toBe('/settings/tools?folder=f1');
    expect(folderPagePath('prompt', 'f1')).toBe('/settings/prompts?folder=f1');
  });
});
