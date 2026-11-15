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
  /** How it reached this list: the caller's, the team's, or shared. */
  origin?: 'own' | 'team' | 'shared' | null;
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
