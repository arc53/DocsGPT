import type { TFunction } from 'i18next';

import type {
  CannotMoveEffect,
  CannotMoveReason,
  MoveErrorBody,
  MoveErrorCode,
  MoveItemType,
  MoveWithReason,
  PersonRef,
} from '../../api/services/workspacesService';

/** Why an item can't come along, as the plan's `cannot_move[].reason`. */
export const CANNOT_MOVE_REASONS: readonly CannotMoveReason[] = [
  'connection_account',
  'connector_synced',
  'custom_model',
  'remote_device',
  'not_yours',
  'in_knowledge_folder',
  'credentials_unreadable',
];

/** What happens to an item that can't come, as `cannot_move[].effect`. */
export const CANNOT_MOVE_EFFECTS: readonly CannotMoveEffect[] = [
  'removed_from_holder',
  'stays',
];

/** Why an item comes along, as `moves_with[].reason`. */
export const MOVE_WITH_REASONS: readonly MoveWithReason[] = [
  'used_by_agent',
  'in_folder',
  'same_workflow',
];

/** Every code a refused plan or move answers with. */
export const MOVE_ERROR_CODES: readonly MoveErrorCode[] = [
  'move_plan_changed',
  'move_would_borrow',
  'move_needs_admin',
  'credentials_unreadable',
  'credentials_unavailable',
  'nothing_to_move',
  'fingerprint_required',
  'folder_too_deep',
  'already_in_workspace',
  'invalid_request',
  'workspace_role_required',
  'not_a_person',
  'workspace_not_found',
  'not_found',
  'folder_not_found',
  'move_failed',
];

/** The kinds a plan names: what moves, plus custom models that can't. */
export const MOVE_KINDS: readonly (MoveItemType | 'model')[] = [
  'agent',
  'source',
  'tool',
  'prompt',
  'folder',
  'model',
];

export const cannotMoveReasonKey = (reason: string): string =>
  `workspace.move.reasons.${
    (CANNOT_MOVE_REASONS as readonly string[]).includes(reason)
      ? reason
      : 'not_yours'
  }`;

export const cannotMoveEffectKey = (effect: string): string =>
  `workspace.move.effects.${effect === 'stays' ? 'stays' : 'removed_from_holder'}`;

export const moveWithReasonKey = (reason: string): string =>
  `workspace.move.withReasons.${
    (MOVE_WITH_REASONS as readonly string[]).includes(reason)
      ? reason
      : 'used_by_agent'
  }`;

/** The message key of a refusal; a code this client doesn't know is a failed move. */
export const moveErrorKey = (code: string): string =>
  `workspace.move.errors.${
    (MOVE_ERROR_CODES as readonly string[]).includes(code)
      ? code
      : 'move_failed'
  }`;

export const moveKindKey = (kind: string): string =>
  `workspace.move.kinds.${
    (MOVE_KINDS as readonly string[]).includes(kind) ? kind : 'agent'
  }`;

const noEscape = { interpolation: { escapeValue: false } };

/**
 * Names as one phrase ("A, B"), quoted, with "N agents you can't open" last
 * when some can only be counted.
 *
 * Args:
 *   t: The translator.
 *   names: The names to list.
 *   others: How many more there are that the caller can't see.
 */
export function nameList(t: TFunction, names: string[], others = 0): string {
  const parts = names.map((name) =>
    t('workspace.move.quoted', { name, ...noEscape }),
  );
  if (others > 0)
    parts.push(t('workspace.move.othersYouCantOpen', { count: others }));
  return parts.join(t('workspace.move.listSeparator'));
}

/**
 * Who pays, as a plan or the share dialog names them: "you" for the caller,
 * else their label, else "someone".
 *
 * Args:
 *   t: The translator.
 *   person: The payer from the server, or null.
 *   me: The caller's user id, when known.
 */
export function payerName(
  t: TFunction,
  person: PersonRef | string | null | undefined,
  me: string | undefined,
): string {
  if (!person) return t('workspace.move.someone');
  const ref = typeof person === 'string' ? { user_id: person } : person;
  if (me && ref.user_id === me) return t('workspace.move.payerYou');
  return ref.label || t('workspace.move.someone');
}

const names = (rows: unknown): string[] =>
  Array.isArray(rows)
    ? rows
        .map((row) => (row as { name?: unknown })?.name)
        .filter((name): name is string => typeof name === 'string' && !!name)
    : [];

/**
 * The text of a borrowing refusal: the agents left behind that use what
 * moves, named when the caller can open them and counted when not.
 *
 * Args:
 *   t: The translator.
 *   direction: `in` to a team, `out` to Personal.
 *   agentNames: The agents the caller can open.
 *   others: How many more the caller can't open.
 *   teamName: The team on the other side of the move.
 */
export function borrowMessage(
  t: TFunction,
  direction: 'in' | 'out',
  agentNames: string[],
  others: number,
  teamName: string,
): string {
  return t(`workspace.move.borrow.${direction}`, {
    count: agentNames.length + others,
    names: nameList(t, agentNames, others),
    team: teamName,
    ...noEscape,
  });
}

/**
 * A refused plan or move as one sentence for the dialog's Alert. Refusals
 * that name agents or tools say which.
 *
 * Args:
 *   t: The translator.
 *   refusal.error: The response's code.
 *   refusal.body: The whole response (its `agents`, `others`, `tools`).
 *   refusal.direction: `in` to a team, `out` to Personal.
 *   refusal.teamName: The team on the other side of the move.
 */
export function moveErrorMessage(
  t: TFunction,
  {
    error,
    body,
    direction,
    teamName,
  }: {
    error: string;
    body?: MoveErrorBody | null;
    direction: 'in' | 'out';
    teamName: string;
  },
): string {
  if (error === 'move_would_borrow') {
    const others = typeof body?.others === 'number' ? body.others : 0;
    const agents = names(body?.agents);
    if (agents.length || others)
      return borrowMessage(t, direction, agents, others, teamName);
  }
  if (error === 'move_needs_admin') {
    const agents = names(body?.agents);
    if (agents.length)
      return t('workspace.move.needsAdmin', {
        count: agents.length,
        names: nameList(t, agents),
        team: teamName,
        ...noEscape,
      });
  }
  if (error === 'credentials_unreadable') {
    const tools = names(body?.tools);
    // The server always names the tools; without them, say it generally.
    if (!tools.length) return t(moveErrorKey('credentials_unavailable'));
    return t(moveErrorKey(error), {
      count: tools.length,
      names: nameList(t, tools),
      ...noEscape,
    });
  }
  return t(moveErrorKey(error), { team: teamName, ...noEscape });
}
