import { describe, expect, it } from 'vitest';

import {
  ADMIN_SECTION,
  getActiveItem,
  getSectionForPath,
  getSectionItems,
  getVisibleGroups,
  SETTINGS_SECTION,
} from './sections';

describe('getSectionForPath', () => {
  it('claims the section root and everything under it', () => {
    expect(getSectionForPath('/settings')?.key).toBe('settings');
    expect(getSectionForPath('/settings/tools')?.key).toBe('settings');
    expect(getSectionForPath('/admin/users')?.key).toBe('admin');
  });

  it('claims routes the section owns outside its root', () => {
    expect(getSectionForPath('/teams')?.key).toBe('settings');
  });

  it('leaves ordinary app routes alone', () => {
    expect(getSectionForPath('/')).toBeNull();
    expect(getSectionForPath('/c/abc123')).toBeNull();
    expect(getSectionForPath('/agents/edit/1')).toBeNull();
  });

  it('matches whole path segments, not string prefixes', () => {
    expect(getSectionForPath('/settings-export')).toBeNull();
    expect(getSectionForPath('/administrators')).toBeNull();
  });
});

describe('getActiveItem', () => {
  it('resolves the section root through the alias', () => {
    expect(getActiveItem(SETTINGS_SECTION, '/settings')?.key).toBe('general');
    expect(getActiveItem(ADMIN_SECTION, '/admin')?.key).toBe('overview');
  });

  it('prefers the deepest match over a shorter alias', () => {
    expect(getActiveItem(SETTINGS_SECTION, '/settings/tools')?.key).toBe(
      'tools',
    );
    expect(
      getActiveItem(SETTINGS_SECTION, '/settings/access-tokens')?.key,
    ).toBe('accessTokens');
  });

  it('keeps the parent item active inside a detail route', () => {
    expect(getActiveItem(SETTINGS_SECTION, '/settings/tools/slack')?.key).toBe(
      'tools',
    );
  });

  it('round-trips every configured item', () => {
    for (const section of [SETTINGS_SECTION, ADMIN_SECTION]) {
      for (const item of getSectionItems(section)) {
        // Items pointing at another section are drill-throughs, not
        // destinations this section can be "on".
        if (item.leavesSection) continue;
        expect(getActiveItem(section, item.path)?.key).toBe(item.key);
      }
    }
  });
});

describe('getVisibleGroups', () => {
  it('hides admin-only entries and the group left empty by them', () => {
    const groups = getVisibleGroups(SETTINGS_SECTION, { isAdmin: false });
    const keys = groups.flatMap((group) => group.items.map((i) => i.key));

    expect(keys).not.toContain('admin');
    expect(groups.map((group) => group.key)).not.toContain('administration');
    expect(keys).toContain('general');
  });

  it('shows them to admins', () => {
    const keys = getVisibleGroups(SETTINGS_SECTION, { isAdmin: true }).flatMap(
      (group) => group.items.map((i) => i.key),
    );

    expect(keys).toContain('admin');
  });
});
