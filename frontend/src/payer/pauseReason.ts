import type { TFunction } from 'i18next';

import { headingLocale } from '../utils/dateTimeUtils';
import type { PausedFor, PersonRef } from './types';

const noEscape = { interpolation: { escapeValue: false } };

/**
 * A day as "1 Dec" in the reader's language, with the year when it is not
 * this year.
 *
 * Args:
 *   value: An ISO timestamp.
 *   language: The UI language code (`jp` reads as Japanese).
 *   options.utc: Read the day in UTC. Quota windows start at 00:00 UTC, so a
 *     reset or an `until` is that UTC day wherever the reader is.
 *
 * Returns:
 *   The date, or an empty string when `value` does not parse.
 */
export function formatPayerDate(
  value: string | null | undefined,
  language?: string,
  { utc = false }: { utc?: boolean } = {},
): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const locale = headingLocale(language === 'jp' ? 'ja' : language);
  const timeZone = utc ? 'UTC' : undefined;
  const year = utc ? date.getUTCFullYear() : date.getFullYear();
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    ...(year !== new Date().getFullYear() && { year: 'numeric' }),
    timeZone,
  }).format(date);
}

/** The user id a team's own principal has; it stands for the team itself. */
const TEAM_PRINCIPAL_PREFIX = '__team__';

/**
 * Who pays, for the reader: their label, and whether it is the reader. The
 * team itself is nobody: a team has no allowance, so a schedule it "pays" for
 * has no payer and must not read "Paid by <team>".
 *
 * Args:
 *   person: `paid_by` from the server.
 *   me: The reader's user id, when known.
 */
export function payerOf(
  person: PersonRef | null | undefined,
  me?: string | null,
): { label: string | null; you: boolean } {
  if (!person || person.user_id?.startsWith(TEAM_PRINCIPAL_PREFIX))
    return { label: null, you: false };
  return {
    label: person.label || null,
    you: !!me && person.user_id === me,
  };
}

/**
 * "Paid by Dana" or "Paid by you", for a schedule's meta line or an outside
 * access row; empty when nobody is named (a personal agent's access).
 *
 * Args:
 *   t: The translate function.
 *   person: `paid_by` from the server.
 *   me: The reader's user id, when known.
 */
export function paidByText(
  t: TFunction,
  person: PersonRef | null | undefined,
  me?: string | null,
): string {
  const payer = payerOf(person, me);
  if (payer.you) return t('payer.common.paidByYou');
  if (!payer.label) return '';
  return t('payer.common.paidBy', { name: payer.label, ...noEscape });
}

const reasonOnly = (
  t: TFunction,
  paused: PausedFor,
  payerLabel: string | null | undefined,
  teamName: string | null | undefined,
  you: boolean,
  language: string | undefined,
): string => {
  const name = payerLabel || null;
  switch (paused.reason) {
    case 'owner_inactive':
      // The agent's owner or the payer; the server doesn't say which.
      return t('payer.common.pause.ownerInactive');
    case 'team_locked':
      // Everyone's way in from outside pauses until the Owner unlocks it.
      return teamName
        ? t('payer.common.pause.teamLocked', { team: teamName, ...noEscape })
        : t('payer.common.pause.teamLockedNoTeam');
    case 'payer_left': {
      // Left the team, still in it with too low a role, or (a stored pause) unknown.
      const key =
        paused.left_team === true
          ? 'payerLeftTeam'
          : paused.left_team === false
            ? 'payerLostRole'
            : 'payerLeft';
      if (!name || you) return t(`payer.common.pause.${key}Unnamed`);
      return teamName
        ? t(`payer.common.pause.${key}`, {
            name,
            team: teamName,
            ...noEscape,
          })
        : t(`payer.common.pause.${key}NoTeam`, { name, ...noEscape });
    }
    case 'no_payer':
      return t('payer.common.pause.noPayer');
    case 'payer_out_of_allowance': {
      const date = formatPayerDate(paused.until, language, { utc: true });
      if (!date) return t('payer.common.pause.outOfAllowanceUndated');
      if (you) return t('payer.common.pause.outOfAllowanceYou', { date });
      return name
        ? t('payer.common.pause.outOfAllowance', { name, date, ...noEscape })
        : t('payer.common.pause.outOfAllowanceUnnamed', { date });
    }
    default:
      return '';
  }
};

/**
 * Why a schedule or an agent's outside access is paused, in one sentence:
 * "Tomas is out of allowance until 1 Dec.", "Ines left Operations.", "Ines
 * no longer has the role in Operations that pays for it.", "Nobody pays for
 * it.", "Operations is locked…". With `since` (the
 * first skipped run) it adds "Paused since 12 Nov.".
 *
 * Args:
 *   t: The translate function.
 *   paused: `paused_for` from the server; null or undefined is not paused.
 *   payerLabel: The payer's label (`paid_by.label`), when known.
 *   teamName: The team the item is in, for `payer_left` and `team_locked`.
 *   options.you: The payer is the reader ("You're out of allowance…").
 *   options.language: The UI language, for the dates.
 *
 * Returns:
 *   The sentence, or an empty string when nothing is paused or the reason is
 *   unknown.
 */
export function pauseReasonText(
  t: TFunction,
  paused: PausedFor | null | undefined,
  payerLabel?: string | null,
  teamName?: string | null,
  { you = false, language }: { you?: boolean; language?: string } = {},
): string {
  if (!paused) return '';
  const reason = reasonOnly(t, paused, payerLabel, teamName, you, language);
  if (!reason) return '';
  const since = formatPayerDate(paused.since, language);
  return since
    ? t('payer.common.pause.withSince', { reason, date: since, ...noEscape })
    : reason;
}
