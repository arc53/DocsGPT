import { describe, expect, it } from 'vitest';

import {
  ADMIN_SECTION,
  AGENTS_SECTION,
  buildAgentSection,
  depthOf,
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
  });

  it('separates managing agents from chatting with one', () => {
    expect(getSectionForPath('/agents/manage')?.key).toBe('agents');
    expect(getSectionForPath('/agents/manage/edit/a1')?.key).toBe('agents');

    // A conversation with an agent must leave the chat list in place.
    expect(getSectionForPath('/agents/a1/c/c1')).toBeNull();
    expect(getSectionForPath('/agents/shared/tok')).toBeNull();
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

describe('AGENTS_SECTION', () => {
  it('gives every list filter its own route', () => {
    expect(getActiveItem(AGENTS_SECTION, '/agents/manage')?.key).toBe('all');
    expect(getActiveItem(AGENTS_SECTION, '/agents/manage/mine')?.key).toBe(
      'user',
    );
    expect(
      getActiveItem(AGENTS_SECTION, '/agents/manage/discovered')?.key,
    ).toBe('shared');
  });
});

describe('buildAgentSection', () => {
  it('is named after the agent and goes back to the list', () => {
    const section = buildAgentSection('a1', 'Support bot', false);

    expect(section.title).toBe('Support bot');
    expect(section.parentPath).toBe('/agents/manage');
  });

  it('falls back to a generic title before the agent has loaded', () => {
    expect(buildAgentSection('a1', undefined, false).title).toBeUndefined();
    expect(buildAgentSection('a1', '   ', false).title).toBeUndefined();
  });

  it('resolves each of the agent pages', () => {
    const section = buildAgentSection('a1', 'Support bot', false);

    expect(getActiveItem(section, '/agents/manage/edit/a1')?.key).toBe(
      'overview',
    );
    expect(getActiveItem(section, '/agents/manage/logs/a1')?.key).toBe('logs');
    expect(getActiveItem(section, '/agents/manage/schedules/a1')?.key).toBe(
      'schedules',
    );
  });

  it('points overview at the workflow builder for a workflow agent', () => {
    const section = buildAgentSection('a1', 'Flow', true);

    expect(section.rootPath).toBe('/agents/manage/workflow/edit/a1');
    expect(getActiveItem(section, '/agents/manage/workflow/edit/a1')?.key).toBe(
      'overview',
    );
  });
});

describe('depthOf', () => {
  it('puts chats, sections and records on their own level', () => {
    expect(depthOf(null)).toBe(0);
    expect(depthOf(getSectionForPath('/settings'))).toBe(1);
    expect(depthOf(getSectionForPath('/agents/manage'))).toBe(1);
    expect(depthOf(getSectionForPath('/admin/users'))).toBe(1);
    expect(depthOf(buildAgentSection('a1', 'Support bot', false))).toBe(2);
  });

  it('keeps a chat with an agent at the chat level', () => {
    expect(depthOf(getSectionForPath('/agents/a1/c/c1'))).toBe(0);
  });
});
