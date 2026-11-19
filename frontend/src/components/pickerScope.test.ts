import type { TFunction } from 'i18next';

import { buildFolderTree } from './folders/folderTree';
import type { Folder } from './folders/types';
import {
  belongsToWorkspace,
  folderTrailOf,
  holderFolderOf,
  scopeToWorkspace,
  splitByHolderFolder,
  workspaceIdOf,
} from './pickerScope';

const t = ((key: string, options?: Record<string, unknown>) =>
  options ? `${key}:${JSON.stringify(options)}` : key) as unknown as TFunction;

const personal = { kind: 'personal' as const, team_id: null };
const team = (id: string) => ({ kind: 'team' as const, team_id: id });

const folder = (id: string, name: string, parent_id: string | null = null) =>
  ({ id, name, parent_id }) as Folder;

describe('workspaceIdOf', () => {
  it('names Personal, a team by its id, and nothing for an unknown one', () => {
    expect(workspaceIdOf(personal)).toBe('personal');
    expect(workspaceIdOf(team('t1'))).toBe('t1');
    expect(workspaceIdOf(undefined)).toBeNull();
    expect(workspaceIdOf(null)).toBeNull();
  });
});

describe('belongsToWorkspace', () => {
  it('keeps a row of the current workspace and a row that names none (a preset, a built-in)', () => {
    expect(belongsToWorkspace({ workspace: team('t1') }, 't1')).toBe(true);
    expect(belongsToWorkspace({ workspace: personal }, 'personal')).toBe(true);
    expect(belongsToWorkspace({ id: 'default' }, 't1')).toBe(true);
  });

  it("drops another workspace's row", () => {
    expect(belongsToWorkspace({ workspace: personal }, 't1')).toBe(false);
    expect(belongsToWorkspace({ workspace: team('t2') }, 't1')).toBe(false);
    expect(belongsToWorkspace({ workspace: team('t1') }, 'personal')).toBe(
      false,
    );
  });
});

describe('scopeToWorkspace', () => {
  const rows = [
    { id: 'mine', workspace: personal },
    { id: 'team', workspace: team('t1') },
    { id: 'preset' },
  ];

  it("lists only the current workspace's rows", () => {
    expect(scopeToWorkspace(rows, 't1').map((row) => row.id)).toEqual([
      'team',
      'preset',
    ]);
    expect(scopeToWorkspace(rows, 'personal').map((row) => row.id)).toEqual([
      'mine',
      'preset',
    ]);
  });

  it('lists nothing of a workspace while the holder lives in another one', () => {
    // A team agent opened while the app still shows Personal's lists.
    expect(
      scopeToWorkspace(rows, 'personal', 't1').map((row) => row.id),
    ).toEqual(['preset']);
    expect(scopeToWorkspace(rows, 't1', 't1').map((row) => row.id)).toEqual([
      'team',
      'preset',
    ]);
  });

  it('reads a missing list as empty', () => {
    expect(scopeToWorkspace(null, 't1')).toEqual([]);
    expect(scopeToWorkspace(undefined, 't1')).toEqual([]);
  });
});

describe('folderTrailOf', () => {
  it("names an item's folder from its own trail, top level first", () => {
    expect(
      folderTrailOf({
        folder_id: 'f2',
        folder_path: [
          { id: 'f1', name: 'Carriers' },
          { id: 'f2', name: 'Rates' },
        ],
      }),
    ).toBe('Carriers › Rates');
  });

  it('falls back to the tree when the item carries no trail', () => {
    const tree = buildFolderTree([
      folder('f1', 'Carriers'),
      folder('f2', 'Rates', 'f1'),
    ]);
    expect(folderTrailOf({ folder_id: 'f2' }, tree)).toBe('Carriers › Rates');
  });

  it('is null for an item in no folder', () => {
    expect(folderTrailOf({ folder_id: null, folder_path: [] })).toBeNull();
    expect(folderTrailOf({})).toBeNull();
  });
});

describe('splitByHolderFolder', () => {
  const rows = [
    { id: 'a', folder_id: null },
    { id: 'b', folder_id: 'f1' },
    { id: 'c', folder_id: 'f2' },
    { id: 'd' },
    { id: 'e', folder_id: 'f1' },
  ];

  it("puts the holder's folder first, then the other folders, then the rest", () => {
    const split = splitByHolderFolder(rows, 'f1');
    expect(split.holder.map((row) => row.id)).toEqual(['b', 'e']);
    expect(split.filed.map((row) => row.id)).toEqual(['c']);
    expect(split.rest.map((row) => row.id)).toEqual(['a', 'd']);
  });

  it('keeps the list as it is for a holder in no folder', () => {
    const split = splitByHolderFolder(rows, null);
    expect(split.holder).toEqual([]);
    expect(split.filed).toEqual([]);
    expect(split.rest.map((row) => row.id)).toEqual(['a', 'b', 'c', 'd', 'e']);
  });
});

describe('holderFolderOf', () => {
  const tree = buildFolderTree([folder('f1', 'Carriers')]);

  it("heads the group with the agent's or the workflow's folder", () => {
    expect(holderFolderOf(t, tree, 'f1', 'agent')).toEqual({
      id: 'f1',
      heading: `workspace.pickers.inAgentFolder:${JSON.stringify({
        folder: 'Carriers',
        interpolation: { escapeValue: false },
      })}`,
    });
    expect(holderFolderOf(t, tree, 'f1', 'workflow')?.heading).toContain(
      'workspace.pickers.inWorkflowFolder',
    );
  });

  it('is null for no folder, or one the tree does not hold', () => {
    expect(holderFolderOf(t, tree, null, 'agent')).toBeNull();
    expect(holderFolderOf(t, tree, 'gone', 'agent')).toBeNull();
  });
});
