import type { TFunction } from 'i18next';

import {
  memberReachesTeamItems,
  shareWarningLines,
  teamItemsLine,
  teamReachesTeamItems,
} from './accessSettings';

const t = ((key: string, opts?: Record<string, unknown>) => {
  if (!opts) return key;
  const params = Object.entries(opts)
    .filter(([k]) => k !== 'interpolation')
    .map(([k, v]) => `${k}=${v}`)
    .join(',');
  return `${key}(${params})`;
}) as unknown as TFunction;

const ops = {
  team_id: 't1',
  name: 'Operations',
  items: [
    { key: 'source:s1', type: 'source' as const, id: 's1', name: 'Rates' },
    { key: 'tool:x1', type: 'tool' as const, id: 'x1', name: null },
  ],
};
const dev = {
  team_id: 't2',
  name: 'Dev',
  items: [
    { key: 'prompt:p1', type: 'prompt' as const, id: 'p1', name: 'Tone' },
  ],
};

describe('shareWarningLines', () => {
  it.each([
    ['agent', 'agent(team=Dev,owner=Operations)'],
    ['source', 'source(team=Dev,owner=Operations)'],
    ['prompt', 'prompt(team=Dev,owner=Operations)'],
    ['tool_stored', 'toolStored(team=Dev,owner=Operations)'],
    ['tool_member', 'toolMember(team=Dev,owner=Operations)'],
  ] as const)('gives the %s line, then the common one', (kind, line) => {
    expect(shareWarningLines(t, kind, 'Dev', 'Operations')).toEqual([
      `workspace.share.outside.warning.${line}`,
      'workspace.share.outside.warning.always(team=Dev)',
    ]);
  });

  it('gives only the common line for a kind it does not know', () => {
    expect(shareWarningLines(t, undefined, 'Dev', 'Operations')).toEqual([
      'workspace.share.outside.warning.always(team=Dev)',
    ]);
  });
});

describe('teamReachesTeamItems', () => {
  it('lets any team through when the agent uses no team items', () => {
    expect(teamReachesTeamItems([], 't9')).toBe(true);
  });

  it('keeps only the team that owns every item', () => {
    expect(teamReachesTeamItems([ops], 't1')).toBe(true);
    expect(teamReachesTeamItems([ops], 't2')).toBe(false);
    // Two teams' items: no single team owns them all.
    expect(teamReachesTeamItems([ops, dev], 't1')).toBe(false);
    expect(teamReachesTeamItems([ops, dev], 't2')).toBe(false);
  });
});

describe('memberReachesTeamItems', () => {
  const members = {
    t1: [{ user_id: 'u1' }, { user_id: 'u2' }],
    t2: [{ user_id: 'u2' }, { user_id: 'u3' }],
  };

  it('lets anyone through when the agent uses no team items', () => {
    expect(memberReachesTeamItems([], members, 'u9')).toBe(true);
  });

  it('keeps only people in every team whose items it uses', () => {
    expect(memberReachesTeamItems([ops], members, 'u1')).toBe(true);
    expect(memberReachesTeamItems([ops], members, 'u3')).toBe(false);
    expect(memberReachesTeamItems([ops, dev], members, 'u2')).toBe(true);
    expect(memberReachesTeamItems([ops, dev], members, 'u1')).toBe(false);
  });

  it("keeps no one for a team whose members aren't known", () => {
    expect(memberReachesTeamItems([ops], {}, 'u1')).toBe(false);
  });
});

describe('teamItemsLine', () => {
  it('names each team and the items the reader can see', () => {
    expect(teamItemsLine(t, [ops, dev])).toBe(
      'workspace.share.outside.uses.fromTeam(team=Operations,items=Rates, ' +
        'workspace.share.outside.uses.hidden(count=1)) ' +
        'workspace.share.outside.uses.fromTeam(team=Dev,items=Tone)',
    );
  });

  it("says another team when the team's name is hidden", () => {
    expect(
      teamItemsLine(t, [
        {
          team_id: 't3',
          name: null,
          items: [{ key: 'tool:x', type: 'tool', id: 'x', name: null }],
        },
      ]),
    ).toBe(
      'workspace.share.outside.uses.fromTeam(team=workspace.share.outside.uses.someTeam,' +
        'items=workspace.share.outside.uses.hidden(count=1))',
    );
  });
});
