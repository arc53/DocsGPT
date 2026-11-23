import { toolPickerItems } from './toolPickerItems';

vi.mock('./ToolIcon', () => ({ default: () => null }));
vi.mock('../connectors/ConnectorIcon', () => ({ default: () => null }));

const t = ((key: string) => key) as never;

const carriers = { id: 'f1', name: 'Carriers' };
const rates = { id: 'f2', name: 'Rates' };

/** Tools of one workspace, some filed in folders. */
const tools = [
  { id: 'loose', name: 'memory', display_name: 'Memory' },
  {
    id: 'mine',
    name: 'api_tool',
    display_name: 'Rate lookup',
    folder_id: 'f1',
    folder_path: [carriers],
  },
  {
    id: 'deeper',
    name: 'memory',
    display_name: 'Notes',
    folder_id: 'f2',
    folder_path: [carriers, rates],
  },
  {
    id: 'builtin',
    name: 'scheduler',
    display_name: 'Scheduler',
    builtin: true,
  },
] as never[];

const build = (extra: Partial<Parameters<typeof toolPickerItems>[1]> = {}) =>
  toolPickerItems(tools, {
    t,
    connections: [],
    catalog: [],
    ...extra,
  });

describe('toolPickerItems folder-first', () => {
  it("lists the holder's folder first, then other folders, then the rest", () => {
    const items = build({
      holderFolder: { id: 'f1', heading: 'In Carriers, this agent’s folder' },
      otherFoldersHeading: 'In other folders',
    });
    expect(items.map((item) => item.id)).toEqual([
      'mine',
      'deeper',
      'builtin',
      'loose',
    ]);
    const [mine, deeper] = items;
    expect(mine.groupHeading).toBe('In Carriers, this agent’s folder');
    expect(deeper.groupHeading).toBe('In other folders');
    // Each group has a key of its own, apart from the kind groups'.
    expect(new Set(items.map((item) => item.group)).size).toBe(4);
    // A tool in another folder says which one.
    expect(deeper.description).toContain('Carriers › Rates');
  });

  it('keeps the kind groups when the holder is in no folder', () => {
    const items = build();
    expect(items.map((item) => item.id)).toEqual([
      'builtin',
      'loose',
      'deeper',
      'mine',
    ]);
    // A tool's folder line shows only while a search is typed.
    expect(items[2].description ?? '').not.toContain('Carriers');
  });

  it("names each tool's folder for a search", () => {
    const items = build();
    const deeper = items.find((item) => item.id === 'deeper')!;
    expect(deeper.folderTrail).toBe('Carriers › Rates');
    expect(items.find((item) => item.id === 'loose')!.folderTrail).toBe(
      undefined,
    );
  });
});
