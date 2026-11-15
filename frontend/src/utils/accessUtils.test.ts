import { describe, expect, it } from 'vitest';

import { can, canOpenShare, isOwner, roleOf } from './accessUtils';

describe('can', () => {
  it('reads allowed_actions from the server', () => {
    const item = {
      access: 'editor' as const,
      allowed_actions: ['edit', 'use'],
    };
    expect(can(item, 'edit')).toBe(true);
    expect(can(item, 'delete')).toBe(false);
  });

  it('treats an item without access fields as the caller’s own', () => {
    // A row created in this session, before the list is refetched.
    expect(can({}, 'delete')).toBe(true);
    expect(can({ access: 'owner' }, 'delete')).toBe(true);
  });

  it('falls back to the role defaults for a shared item without an action list', () => {
    // An API older than the frontend sends only the legacy team fields.
    const viewer = {
      ownership: 'team' as const,
      team_access: 'viewer' as const,
    };
    expect(can(viewer, 'pin')).toBe(true);
    expect(can(viewer, 'use')).toBe(true);
    expect(can(viewer, 'view_config')).toBe(true);
    expect(can(viewer, 'edit')).toBe(false);
    const editor = { access: 'editor' as const };
    expect(can(editor, 'edit')).toBe(true);
    expect(can(editor, 'view_logs')).toBe(true);
    expect(can(editor, 'delete')).toBe(false);
    expect(can(editor, 'share')).toBe(false);
    expect(can(editor, 'manage_settings')).toBe(false);
    // Keys, public links and webhooks wait for the owner's switch.
    expect(can(editor, 'manage_access_details')).toBe(false);
  });

  it('denies a missing item', () => {
    expect(can(null, 'use')).toBe(false);
    expect(can(undefined, 'use')).toBe(false);
  });
});

describe('roleOf / isOwner', () => {
  it('prefers access, then the legacy team fields', () => {
    expect(roleOf({ access: 'viewer' })).toBe('viewer');
    expect(roleOf({ ownership: 'team', team_access: 'editor' })).toBe('editor');
    expect(roleOf({ ownership: 'team' })).toBe('viewer');
    expect(roleOf({})).toBe('owner');
    expect(isOwner({ access: 'editor' })).toBe(false);
    expect(isOwner({})).toBe(true);
  });
});

describe('canOpenShare', () => {
  it('follows the share action on a personal item', () => {
    expect(
      canOpenShare({ access: 'owner', allowed_actions: ['share', 'use'] }),
    ).toBe(true);
    expect(
      canOpenShare({
        access: 'viewer',
        origin: 'shared',
        allowed_actions: ['use'],
      }),
    ).toBe(false);
  });

  it("opens a team item's Share for any member, to see where access comes from", () => {
    // A team role never has `share`: the dialog is read-only for them.
    expect(
      canOpenShare({
        access: 'viewer',
        origin: 'team',
        allowed_actions: ['use'],
      }),
    ).toBe(true);
    expect(
      canOpenShare({
        access: 'editor',
        workspace: { kind: 'team', team_id: 't1' },
        allowed_actions: ['use', 'edit'],
      }),
    ).toBe(true);
  });
});
