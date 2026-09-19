import { describe, expect, it } from 'vitest';

import {
  buildResourceFilter,
  countLiveTokens,
  defaultExpiry,
  eligibleFilterFamilies,
  expiryOptions,
  expiryStatus,
  groupScopesByFamily,
  isScopeImplied,
  isUuid,
  NO_EXPIRY,
  relativeTime,
  restrictionCounts,
  scopesToSubmit,
  toResourceOptions,
} from './accessTokenUtils';

const CATALOG = [
  { name: 'agents:read', description: 'View agents' },
  { name: 'agents:write', description: 'Edit agents' },
  { name: 'agents:keys', description: 'Agent keys' },
  { name: 'sources:read', description: 'View sources' },
  { name: 'analytics:read', description: 'View analytics' },
  { name: 'chat:run', description: 'Ask agents' },
];
const FAMILIES = ['agents', 'sources', 'prompts', 'tools', 'workflows'];
const POLICY = {
  default_lifetime_days: 90,
  max_lifetime_days: 365,
  allow_non_expiring: false,
};
const NOW = Date.parse('2026-09-19T12:00:00Z');
const DAY = 24 * 60 * 60 * 1000;
const ID_A = '11111111-1111-4111-8111-111111111111';
const ID_B = '22222222-2222-4222-8222-222222222222';

describe('groupScopesByFamily', () => {
  it('groups by family in catalog order', () => {
    const groups = groupScopesByFamily(CATALOG);
    expect(groups.map((g) => g.family)).toEqual([
      'agents',
      'sources',
      'analytics',
      'chat',
    ]);
    expect(groups[0].scopes.map((s) => s.name)).toEqual([
      'agents:read',
      'agents:write',
      'agents:keys',
    ]);
  });
});

describe('scope implication', () => {
  it('write implies read of the same family only', () => {
    expect(isScopeImplied('agents:read', ['agents:write'])).toBe(true);
    expect(isScopeImplied('sources:read', ['agents:write'])).toBe(false);
    expect(isScopeImplied('agents:keys', ['agents:write'])).toBe(false);
    expect(isScopeImplied('agents:write', ['agents:write'])).toBe(false);
    expect(isScopeImplied('agents:read', ['agents:read'])).toBe(false);
  });

  it('scopesToSubmit drops implied reads and keeps catalog order', () => {
    expect(
      scopesToSubmit(
        ['chat:run', 'agents:write', 'agents:read', 'sources:read'],
        CATALOG,
      ),
    ).toEqual(['agents:write', 'sources:read', 'chat:run']);
  });

  it('scopesToSubmit ignores scopes missing from the catalog', () => {
    expect(scopesToSubmit(['bogus:read', 'agents:read'], CATALOG)).toEqual([
      'agents:read',
    ]);
  });
});

describe('eligibleFilterFamilies', () => {
  it('only offers families that have a selected scope', () => {
    expect(eligibleFilterFamilies(['sources:read'], FAMILIES)).toEqual([
      'sources',
    ]);
    expect(eligibleFilterFamilies(['analytics:read'], FAMILIES)).toEqual([]);
    expect(eligibleFilterFamilies([], FAMILIES)).toEqual([]);
  });

  it('chat:run additionally permits agents and sources', () => {
    expect(eligibleFilterFamilies(['chat:run'], FAMILIES)).toEqual([
      'agents',
      'sources',
    ]);
  });

  it('respects the families the server says are filterable', () => {
    expect(eligibleFilterFamilies(['chat:run'], ['sources'])).toEqual([
      'sources',
    ]);
  });
});

describe('buildResourceFilter', () => {
  it('drops empty and ineligible families', () => {
    expect(
      buildResourceFilter({ agents: [ID_A], sources: [], tools: [ID_B] }, [
        'agents',
        'sources',
      ]),
    ).toEqual({ agents: [ID_A] });
  });

  it('returns undefined when nothing is restricted', () => {
    expect(buildResourceFilter({ agents: [] }, ['agents'])).toBeUndefined();
    expect(buildResourceFilter({}, [])).toBeUndefined();
  });
});

describe('restrictionCounts', () => {
  it('counts ids per family', () => {
    expect(
      restrictionCounts({ agents: [ID_A, ID_B], sources: [ID_A] }),
    ).toEqual([
      { family: 'agents', count: 2 },
      { family: 'sources', count: 1 },
    ]);
  });

  it('is empty ("all resources") for no filter', () => {
    expect(restrictionCounts({})).toEqual([]);
    expect(restrictionCounts(null)).toEqual([]);
    expect(restrictionCounts({ agents: [] })).toEqual([]);
  });
});

describe('expiryOptions / defaultExpiry', () => {
  it('offers every preset up to the maximum', () => {
    expect(expiryOptions(POLICY)).toEqual([7, 30, 60, 90, 180, 365]);
    expect(defaultExpiry(POLICY)).toBe(90);
  });

  it('filters presets above max_lifetime_days', () => {
    expect(expiryOptions({ ...POLICY, max_lifetime_days: 90 })).toEqual([
      7, 30, 60, 90,
    ]);
  });

  it('adds a non-preset default in sorted position', () => {
    const policy = { ...POLICY, default_lifetime_days: 45 };
    expect(expiryOptions(policy)).toEqual([7, 30, 45, 60, 90, 180, 365]);
    expect(defaultExpiry(policy)).toBe(45);
  });

  it('appends "no expiration" only when allowed', () => {
    const options = expiryOptions({ ...POLICY, allow_non_expiring: true });
    expect(options[options.length - 1]).toBe(NO_EXPIRY);
    expect(expiryOptions(POLICY)).not.toContain(NO_EXPIRY);
  });

  it('falls back to the longest allowed lifetime for an out-of-range default', () => {
    const policy = {
      ...POLICY,
      default_lifetime_days: 400,
      max_lifetime_days: 60,
    };
    expect(expiryOptions(policy)).toEqual([7, 30, 60]);
    expect(defaultExpiry(policy)).toBe(60);
  });

  it('never returns an empty list when the maximum is below every preset', () => {
    const policy = {
      ...POLICY,
      default_lifetime_days: 90,
      max_lifetime_days: 3,
    };
    expect(expiryOptions(policy)).toEqual([3]);
    expect(defaultExpiry(policy)).toBe(3);
  });
});

describe('expiryStatus', () => {
  const at = (offset: number) => new Date(NOW + offset).toISOString();

  it('classifies expiry relative to now', () => {
    expect(expiryStatus(null, NOW)).toBe('never');
    expect(expiryStatus(at(-1000), NOW)).toBe('expired');
    expect(expiryStatus(at(3 * DAY), NOW)).toBe('expiringSoon');
    expect(expiryStatus(at(7 * DAY), NOW)).toBe('expiringSoon');
    expect(expiryStatus(at(7 * DAY + 60_000), NOW)).toBe('ok');
  });

  it('does not flag an unparseable date', () => {
    expect(expiryStatus('not-a-date', NOW)).toBe('ok');
  });

  it('countLiveTokens skips expired tokens, like the server cap', () => {
    expect(
      countLiveTokens(
        [
          { expires_at: null },
          { expires_at: at(DAY) },
          { expires_at: at(-DAY) },
        ],
        NOW,
      ),
    ).toBe(2);
  });
});

describe('relativeTime', () => {
  const ago = (ms: number) => new Date(NOW - ms).toISOString();

  it('buckets past timestamps', () => {
    expect(relativeTime(null, NOW)).toBeNull();
    expect(relativeTime('garbage', NOW)).toBeNull();
    expect(relativeTime(ago(20_000), NOW)).toEqual({ unit: 'now' });
    expect(relativeTime(ago(5 * 60_000), NOW)).toEqual({
      unit: 'minutes',
      count: 5,
    });
    expect(relativeTime(ago(3 * 3_600_000), NOW)).toEqual({
      unit: 'hours',
      count: 3,
    });
    expect(relativeTime(ago(2 * DAY), NOW)).toEqual({ unit: 'days', count: 2 });
    expect(relativeTime(ago(45 * DAY), NOW)).toEqual({ unit: 'date' });
  });

  it('treats clock skew into the future as "now"', () => {
    expect(relativeTime(ago(-30_000), NOW)).toEqual({ unit: 'now' });
  });
});

describe('toResourceOptions', () => {
  it('accepts only UUID ids', () => {
    expect(isUuid(ID_A)).toBe(true);
    expect(isUuid('default')).toBe(false);
    expect(isUuid(undefined)).toBe(false);
  });

  it('keeps own items with UUID ids, sorted by label', () => {
    expect(
      toResourceOptions('sources', [
        { id: ID_B, name: 'Zeta' },
        { id: 'default', name: 'Default' },
        { id: ID_A, name: 'Alpha', ownership: 'user' },
        {
          id: '33333333-3333-4333-8333-333333333333',
          name: 'Team',
          ownership: 'team',
        },
      ]),
    ).toEqual([
      { value: ID_A, label: 'Alpha' },
      { value: ID_B, label: 'Zeta' },
    ]);
  });

  it('skips built-in and team prompts', () => {
    expect(
      toResourceOptions('prompts', [
        { id: 'default', name: 'default', type: 'public' },
        { id: ID_A, name: 'Mine', type: 'private' },
        { id: ID_B, name: 'Shared', type: 'team' },
      ]),
    ).toEqual([{ value: ID_A, label: 'Mine' }]);
  });

  it('reads tools from the {tools: []} envelope and prefers the custom name', () => {
    expect(
      toResourceOptions('tools', {
        success: true,
        tools: [
          {
            id: ID_A,
            name: 'brave',
            displayName: 'Brave',
            customName: 'My search',
          },
        ],
      }),
    ).toEqual([{ value: ID_A, label: 'My search' }]);
  });

  it('returns nothing for an error body', () => {
    expect(toResourceOptions('agents', { success: false })).toEqual([]);
  });
});
