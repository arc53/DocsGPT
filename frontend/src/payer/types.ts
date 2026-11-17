import type { PersonRef } from '../api/services/workspacesService';

export type { PersonRef };

/**
 * Why something a person pays for is paused, most important first: the
 * owner's or payer's account is off, the team is locked (outside access
 * only), the payer left the team or lost the role, nobody pays, or the payer
 * is out of allowance until the reset.
 */
export type PauseReason =
  | 'owner_inactive'
  | 'team_locked'
  | 'payer_left'
  | 'no_payer'
  | 'payer_out_of_allowance';

export const PAUSE_REASONS: readonly PauseReason[] = [
  'owner_inactive',
  'team_locked',
  'payer_left',
  'no_payer',
  'payer_out_of_allowance',
];

/**
 * `paused_for` on a schedule, an agent's outside access and the team Usage
 * report's paused list. Null on the item when it is not paused.
 */
export type PausedFor = {
  reason: PauseReason;
  /** ISO; set only for `payer_out_of_allowance` (the allowance's reset). */
  until?: string | null;
  /** ISO of the first skipped run (schedules only), or null. */
  since?: string | null;
  /**
   * For `payer_left`: true when the payer left the team, false when they are
   * still in it with a role too low to pay. Absent when the server can't say
   * (a stored pause), which reads as either.
   */
  left_team?: boolean | null;
};

/** One way an agent answers from outside the app. */
export type OutsideAccessKind = 'api_key' | 'public_link' | 'webhook';

export const OUTSIDE_ACCESS_KINDS: readonly OutsideAccessKind[] = [
  'api_key',
  'public_link',
  'webhook',
];

/**
 * An agent's `outside_access` (`get_agent`, for callers who can manage
 * access; the team share dialog). `paid_by` is null on a personal agent,
 * whose owner always pays.
 */
export type OutsideAccess = {
  api_key: boolean;
  public_link: boolean;
  webhook: boolean;
  paid_by?: PersonRef | null;
  paused_for?: Pick<PausedFor, 'reason' | 'until' | 'left_team'> | null;
  /** The caller may take it over: a team agent, an Admin, not the payer. */
  can_take_over?: boolean;
};

/** The payer fields every schedule read carries. */
export type SchedulePayerFields = {
  paid_by?: PersonRef | null;
  paused_for?: PausedFor | null;
  /** The caller may take it over: a team agent, an Editor, not the payer. */
  can_take_over?: boolean;
};

/** A source's `sync_paused`: its scheduled sync has nobody to pay for it. */
export type SourceSyncPaused = {
  reason: 'sync_no_payer' | string;
  since?: string | null;
};

/** Whether a value read from the server is a known pause. */
export const isPausedFor = (value: unknown): value is PausedFor =>
  !!value &&
  typeof value === 'object' &&
  PAUSE_REASONS.includes((value as { reason?: unknown }).reason as PauseReason);
