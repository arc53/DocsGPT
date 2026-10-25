import { describe, expect, it } from 'vitest';

import {
  ACTIVITY_SECTION,
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

describe('activity section', () => {
  it('owns /activity and lists schedules and monitors as automations', () => {
    expect(getSectionForPath('/activity')?.key).toBe('activity');
    expect(getSectionForPath('/activity/monitors')?.key).toBe('activity');
    const groups = getVisibleGroups(ACTIVITY_SECTION, { isAdmin: false });
    expect(groups[0].items.map((i) => i.key)).toEqual([
      'now',
      'calendar',
      'history',
    ]);
    const automations = groups.find((group) => group.key === 'automations');
    expect(automations?.items.map((i) => i.key)).toEqual([
      'schedules',
      'monitors',
    ]);
  });

  it('marks Now active on the section root', () => {
    expect(getActiveItem(ACTIVITY_SECTION, '/activity')?.key).toBe('now');
  });

  it('leaves monitors out of settings', () => {
    const keys = getSectionItems(SETTINGS_SECTION).map((i) => i.key);
    expect(keys).not.toContain('monitors');
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
    expect(getActiveItem(section, '/agents/manage/analytics/a1')?.key).toBe(
      'analytics',
    );
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

  it('points overview at the builder from a workflow agent’s other pages', () => {
    // The monitoring paths don't say the agent is a workflow; its record does.
    const section = buildAgentSection('a1', 'Flow', false, {
      access: 'owner',
      agent_type: 'workflow',
    });

    expect(section.rootPath).toBe('/agents/manage/workflow/edit/a1');
    expect(getActiveItem(section, '/agents/manage/workflow/edit/a1')?.key).toBe(
      'overview',
    );
  });

  // The classic edit path still renders a workflow (an old link, a fallback
  // when the agent isn't loaded): Overview stays the active tab there.
  it('keeps overview active on a workflow agent’s classic edit path', () => {
    const section = buildAgentSection('a1', 'Flow', false, {
      access: 'owner',
      agent_type: 'workflow',
    });

    expect(getActiveItem(section, '/agents/manage/edit/a1')?.key).toBe(
      'overview',
    );
    expect(section.matches).toContain('/agents/manage/edit/a1');
  });
});

describe('buildAgentSection tabs for a draft', () => {
  it('shows only Overview until the agent is published', () => {
    const items = getSectionItems(
      buildAgentSection('a1', 'Bot', false, {
        access: 'owner',
        status: 'draft',
        allowed_actions: ['view', 'view_logs', 'manage_schedules'],
      }),
    ).map((item) => item.key);
    expect(items).toEqual(['overview']);
  });
});

describe('buildAgentSection tabs by role', () => {
  const keys = (actions?: string[]) =>
    getSectionItems(
      buildAgentSection(
        'a1',
        'Bot',
        false,
        actions ? { access: 'editor', allowed_actions: actions } : undefined,
      ),
    ).map((item) => item.key);

  it('shows every tab before the agent has loaded', () => {
    expect(keys()).toEqual([
      'overview',
      'schedules',
      'analytics',
      'insights',
      'logs',
    ]);
  });

  it('shows an editor every tab', () => {
    expect(keys(['view', 'view_logs', 'manage_schedules'])).toEqual([
      'overview',
      'schedules',
      'analytics',
      'insights',
      'logs',
    ]);
  });

  it('shows a viewer no tabs, or Monitoring when the owner shares logs', () => {
    expect(keys(['pin', 'use'])).toEqual([]);
    expect(keys(['pin', 'use', 'view_logs'])).toEqual([
      'analytics',
      'insights',
      'logs',
    ]);
  });

  it('hides Insights while the server labels no conversations', () => {
    const visible = (analytics: boolean) =>
      getVisibleGroups(buildAgentSection('a1', 'Bot', false), {
        features: { analytics },
      })
        .flatMap((group) => group.items)
        .map((item) => item.key);
    expect(visible(false)).toEqual([
      'overview',
      'schedules',
      'analytics',
      'logs',
    ]);
    expect(visible(true)).toContain('insights');
  });

  it('owns the agent insights and analytics routes', () => {
    const section = buildAgentSection('a1', 'Bot', false);
    expect(getActiveItem(section, '/agents/manage/insights/a1')?.key).toBe(
      'insights',
    );
    expect(getActiveItem(section, '/agents/manage/analytics/a1')?.key).toBe(
      'analytics',
    );
    expect(getSectionForPath('/agents/manage/analytics/a1')?.key).toBe(
      'agents',
    );
  });
});

describe('buildAgentSection groups', () => {
  const groups = (actions?: string[]) =>
    getVisibleGroups(
      buildAgentSection(
        'a1',
        'Bot',
        false,
        actions ? { access: 'editor', allowed_actions: actions } : undefined,
      ),
    ).map((group) => ({
      key: group.key,
      labelKey: group.labelKey,
      items: group.items.map((item) => item.key),
    }));

  it('puts the pages that watch the agent under Monitoring', () => {
    expect(groups()).toEqual([
      { key: 'agent', labelKey: undefined, items: ['overview', 'schedules'] },
      {
        key: 'monitoring',
        labelKey: 'navigation.sections.groups.monitoring',
        items: ['analytics', 'insights', 'logs'],
      },
    ]);
  });

  it('drops a group the role leaves empty', () => {
    expect(groups(['pin', 'use', 'view_logs']).map((g) => g.key)).toEqual([
      'monitoring',
    ]);
    expect(groups(['view']).map((g) => g.key)).toEqual(['agent']);
  });
});

describe('SETTINGS_SECTION Monitoring', () => {
  it('holds Analytics, Insights and Logs', () => {
    const monitoring = SETTINGS_SECTION.groups.find(
      (group) => group.key === 'monitoring',
    );
    expect(monitoring?.labelKey).toBe('navigation.sections.groups.monitoring');
    expect(monitoring?.items.map((item) => item.key)).toEqual([
      'analytics',
      'insights',
      'logs',
    ]);
    expect(
      SETTINGS_SECTION.groups.some((group) => group.key === 'insights'),
    ).toBe(false);
  });

  it('routes Insights to its own page, hidden while the server has it off', () => {
    expect(getActiveItem(SETTINGS_SECTION, '/settings/insights')?.key).toBe(
      'insights',
    );
    const keys = (analytics: boolean) =>
      getVisibleGroups(SETTINGS_SECTION, { features: { analytics } })
        .find((group) => group.key === 'monitoring')
        ?.items.map((item) => item.key);
    expect(keys(false)).toEqual(['analytics', 'logs']);
    expect(keys(true)).toEqual(['analytics', 'insights', 'logs']);
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
