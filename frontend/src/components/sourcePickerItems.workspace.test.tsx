import type { Doc } from '../models/misc';
import type { KnowledgePick } from './folders/folderPick';
import { buildFolderTree } from './folders/folderTree';
import { buildKnowledgeRows } from './folders/knowledgeFolderRows';
import type { Folder } from './folders/types';
import { toSourcePickerItem, withHolderFolderFirst } from './sourcePickerItems';

vi.mock('../connectors/ConnectorIcon', () => ({ default: () => null }));

const t = ((key: string, opts?: Record<string, unknown>) => {
  const { interpolation: _i, ...rest } = opts ?? {};
  void _i;
  return Object.keys(rest).length ? `${key}:${JSON.stringify(rest)}` : key;
}) as never;

const labels = { own: 'Yours', team: 'Shared with team' };
const folder = (id: string, name: string): Folder => ({
  id,
  name,
  parent_id: null,
  counts: { source: 1 },
});
const doc = (id: string, folderId: string | null): Doc => ({
  id,
  name: `Doc ${id}`,
  date: '',
  model: 'm',
  folder_id: folderId,
});

const tree = buildFolderTree([folder('f1', 'Carriers'), folder('f2', 'Rates')]);
const docs = [doc('inHolder', 'f1'), doc('loose', null), doc('other', 'f2')];
const sourceRow = (item: Doc, linePrefix: string | null) =>
  toSourcePickerItem(item, { t, labels, connections: [], linePrefix });
const holderFolder = { id: 'f1', heading: 'In Carriers, this agent’s folder' };

/** The picker's root rows, as the folder-aware knowledge picker draws them. */
const rootRows = (pick: KnowledgePick) =>
  buildKnowledgeRows({
    t,
    tree,
    docs,
    shownDocs: docs,
    pick,
    place: null,
    query: '',
    kindFiltered: false,
    sourceRow,
    onOpen: () => undefined,
  });

const lead = (pick: KnowledgePick, folderFirst = holderFolder) =>
  withHolderFolderFirst(rootRows(pick), {
    t,
    holderFolder: folderFirst,
    tree,
    docs,
    pick,
    sourceRow,
  });

describe('withHolderFolderFirst', () => {
  it("lists the holder's folder's sources first, then the folders, then the rest", () => {
    const rows = lead({ sources: [], folders: [] });
    expect(rows.map((row) => row.id)).toEqual([
      'inHolder',
      'folder:f1',
      'folder:f2',
      'loose',
    ]);
    expect(rows[0].group).not.toBe(rows[1].group);
    expect(rows[0].groupHeading).toBe('In Carriers, this agent’s folder');
  });

  it('lists a picked source of the folder once', () => {
    // At the root a filed source that is picked has a Selected-only row;
    // the folder's group holds it now.
    const rows = lead({ sources: ['inHolder'], folders: [] });
    expect(rows.filter((row) => row.id === 'inHolder')).toHaveLength(1);
    expect(rows[0]).toMatchObject({ id: 'inHolder' });
    expect(rows[0].pinnedOnly).toBeFalsy();
  });

  it('marks the sources a picked folder brings in', () => {
    const rows = lead({ sources: [], folders: ['f1'] });
    expect(rows[0]).toMatchObject({
      id: 'inHolder',
      checked: true,
      muted: true,
      disabled: true,
    });
  });

  it("puts another team's sources after the team's own at the root", () => {
    const received: Doc = {
      ...doc('received', null),
      origin: 'team_shared',
      ownership: 'team',
      shared_from: { team_id: 'sales', name: 'Sales' },
    };
    const rows = buildKnowledgeRows({
      t,
      tree,
      docs: [...docs, received],
      shownDocs: [received, ...docs],
      pick: { sources: [], folders: [] },
      place: null,
      query: '',
      kindFiltered: false,
      sourceRow,
      onOpen: () => undefined,
    });
    const last = rows[rows.length - 1];
    expect(last.id).toBe('received');
    expect(last.group).toBe('workspace.page.sharedFromTeams.title');
  });

  it('leaves the rows alone for a holder in no folder', () => {
    const base = rootRows({ sources: [], folders: [] });
    expect(
      withHolderFolderFirst(base, {
        t,
        holderFolder: null,
        tree,
        docs,
        pick: { sources: [], folders: [] },
        sourceRow,
      }),
    ).toBe(base);
  });
});
