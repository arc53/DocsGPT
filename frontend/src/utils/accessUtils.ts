import type { ItemOrigin, SharedFrom } from '../workspace/itemOrigin';

/**
 * Access to a team-shared resource (agent, source, tool, prompt).
 *
 * The backend resolves the caller's role and the owner's per-asset switches
 * and sends the result on every list and get response as `access` plus
 * `allowed_actions` (`docsgpt/api/user/resource_access.py`). The UI only asks
 * `can(item, action)`; it never re-derives the rules from the role.
 */
export type Access = 'owner' | 'admin' | 'editor' | 'viewer';

export type AccessFields = {
  /** `admin` only on a team item, for the team's Owner and Admins. */
  access?: Access | null;
  allowed_actions?: string[];
  /** Where the item lives. */
  workspace?: { kind: 'personal' | 'team'; team_id?: string | null } | null;
  /** How it reached this list (see `ItemOrigin`): the caller's, the team's, shared, or an agent's public link. */
  origin?: ItemOrigin | null;
  /** `team_shared` items: the team that owns and shared it. */
  shared_from?: SharedFrom | null;
  /** Who added it; on a personal item, its owner. */
  created_by?: { user_id?: string | null; label?: string | null } | null;
  /** The caller's role in the item's team (team items). */
  team_role?: 'owner' | 'admin' | 'editor' | 'viewer' | null;
  /** Legacy fields, still sent: `team` marks a resource shared with you. */
  ownership?: 'user' | 'team';
  team_access?: 'viewer' | 'editor' | null;
};

/** The caller's role on an item; an item with no access fields is their own. */
export function roleOf(item: AccessFields): Access {
  if (item.access) return item.access;
  if (item.ownership === 'team') return item.team_access ?? 'viewer';
  return 'owner';
}

export function isOwner(item: AccessFields): boolean {
  return roleOf(item) === 'owner';
}

/**
 * Each role's default actions, used only when a shared item arrives without
 * `allowed_actions` (an API older than this frontend). Mirrors the defaults
 * of `ACTIONS` in `docsgpt/api/user/resource_access.py`; action names don't
 * collide across resource types, so one table covers all four. Owner-only
 * actions (share, delete, move, settings) are never in it, nor
 * `manage_access_details`, which an agent's owner must switch on for editors.
 */
const VIEWER_DEFAULTS = [
  'use',
  'pin',
  'use_in_own',
  'view_config',
  'duplicate',
];
const EDITOR_DEFAULTS = [
  ...VIEWER_DEFAULTS,
  'view',
  'edit',
  'publish',
  'edit_policy',
  'view_logs',
  'manage_schedules',
  'export',
  'edit_credentials',
];
const ROLE_DEFAULTS: Record<Exclude<Access, 'owner'>, ReadonlySet<string>> = {
  viewer: new Set(VIEWER_DEFAULTS),
  editor: new Set(EDITOR_DEFAULTS),
  // A team item's Admin also deletes it, moves it out and manages it.
  admin: new Set([
    ...EDITOR_DEFAULTS,
    'manage_access_details',
    'delete',
    'move_out',
    'reconnect',
  ]),
};

/**
 * Whether the caller may perform `action` on `item`.
 *
 * Uses the server's `allowed_actions` when present. Without it the caller's
 * own items allow everything (a row created in this session, before a
 * refetch), and a shared item gets its role's defaults, so a stale API
 * degrades to sensible menus rather than empty ones.
 */
export function can(
  item: AccessFields | null | undefined,
  action: string,
): boolean {
  if (!item) return false;
  if (item.allowed_actions) return item.allowed_actions.includes(action);
  const role = roleOf(item);
  return role === 'owner' || ROLE_DEFAULTS[role].has(action);
}

/**
 * Whether the caller may publish an agent or workflow. One read from the
 * server answers with its own access fields; a new one, or one saved in this
 * session, carries none and lands in the current workspace, where publishing
 * a team's agent is an Admin's (outward exposure belongs to the team).
 *
 * Args:
 *   item: The agent, with its access fields when it has them.
 *   workspaceRole: The caller's role in the current workspace (`owner` in
 *     Personal); null without a workspace, which reads as Personal.
 *
 * Returns:
 *   True when the server would let the caller publish it.
 */
export function canPublish(
  item: AccessFields | null | undefined,
  workspaceRole: string | null | undefined,
): boolean {
  if (!item) return false;
  if (item.allowed_actions || item.access || item.ownership)
    return can(item, 'publish');
  return (
    !workspaceRole || workspaceRole === 'owner' || workspaceRole === 'admin'
  );
}

/**
 * Whether the item's ⋯ offers Share. A personal item follows `share`; a
 * team's item offers it to every member, read-only for most, since the
 * dialog then says where its access comes from rather than changing it.
 *
 * Args:
 *   item: The item, with its access and workspace fields.
 *
 * Returns:
 *   True when Share belongs in the item's menu.
 */
export function canOpenShare(item: AccessFields | null | undefined): boolean {
  if (!item) return false;
  if (item.origin === 'team' || item.workspace?.kind === 'team') return true;
  return can(item, 'share');
}
