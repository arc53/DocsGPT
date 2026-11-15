import {
  type PickerPrompt,
  promptKindOf,
  promptPickerGroups,
} from './promptPickerGroups';

const prompt = (
  id: string,
  extra: Partial<PickerPrompt> = {},
): PickerPrompt => ({
  id,
  name: `Prompt ${id}`,
  type: 'private',
  origin: 'own',
  ...extra,
});

const carriers = { id: 'f1', name: 'Carriers' };
const rates = { id: 'f2', name: 'Rates' };

const PROMPTS: PickerPrompt[] = [
  { id: 'default', name: 'default', type: 'public' },
  prompt('loose'),
  prompt('mine', { folder_id: 'f1', folder_path: [carriers] }),
  prompt('deeper', { folder_id: 'f2', folder_path: [carriers, rates] }),
  prompt('theirs', { type: 'team', origin: 'shared' }),
];

const build = (searching = false, holder = true) =>
  promptPickerGroups({
    prompts: PROMPTS,
    headingOf: (kind) => `kind:${kind}`,
    lineOf: () => undefined,
    holderFolder: holder ? { id: 'f1', heading: 'In Carriers' } : null,
    otherFoldersHeading: 'In other folders',
    searching,
  });

const shape = (groups: ReturnType<typeof build>) =>
  groups.map((group) => [
    group.heading,
    group.options.map((option) => option.value),
  ]);

describe('promptPickerGroups', () => {
  it("lists the agent's folder first, then other folders, then the kinds", () => {
    expect(shape(build())).toEqual([
      ['In Carriers', ['mine']],
      ['In other folders', ['deeper']],
      ['kind:included', ['default']],
      ['kind:yours', ['loose']],
      ['kind:shared', ['theirs']],
    ]);
    // Under other folders each row says which one.
    expect(build()[1].options[0].description).toBe('Carriers › Rates');
  });

  it('keeps the kinds for an agent in no folder', () => {
    expect(shape(build(false, false))).toEqual([
      ['kind:included', ['default']],
      ['kind:yours', ['loose', 'mine', 'deeper']],
      ['kind:shared', ['theirs']],
    ]);
  });

  it('lists the kinds while a search is typed, each row naming its folder', () => {
    const groups = build(true);
    expect(shape(groups)[0]).toEqual(['kind:included', ['default']]);
    const deeper = groups
      .flatMap((group) => group.options)
      .find((option) => option.value === 'deeper')!;
    expect(deeper.description).toBe('Carriers › Rates');
    expect(deeper.keywords).toEqual(['Carriers › Rates']);
  });
});

describe('promptKindOf', () => {
  it("reads a team's prompt as the workspace's own, not shared", () => {
    expect(promptKindOf(prompt('t', { type: 'team', origin: 'team' }))).toBe(
      'yours',
    );
    expect(promptKindOf(prompt('s', { type: 'team', origin: 'shared' }))).toBe(
      'shared',
    );
    // An older server sends no origin: the type decides.
    expect(promptKindOf(prompt('o', { type: 'team', origin: undefined }))).toBe(
      'shared',
    );
    expect(
      promptKindOf({ id: 'default', name: 'default', type: 'public' }),
    ).toBe('included');
  });
});
