import { decodeJwtPayload } from './jwtUtils';

/**
 * A person as the API names them: a team member (`email`) or a person on an
 * agent's read (`label`, their email when on file, else their user id).
 */
export type PersonLike = {
  user_id?: string | null;
  email?: string | null;
  label?: string | null;
};

/**
 * A long user id (an OIDC sub) with its middle cut out, keeping both ends
 * identifiable. There is no display-name endpoint, so this is the fallback
 * when no email is on file.
 *
 * Args:
 *   sub: The user id.
 *
 * Returns:
 *   The id itself up to 24 characters, else its first 12 and last 8.
 */
export function truncateSub(sub: string): string {
  return sub.length > 24 ? `${sub.slice(0, 12)}…${sub.slice(-8)}` : sub;
}

/** Whether the person is the reader; never without a reader id. */
export function isReader(
  person: PersonLike | null | undefined,
  readerId: string | undefined,
): boolean {
  return Boolean(readerId && person?.user_id && person.user_id === readerId);
}

/**
 * The one way the app names a person: "You" for the reader, else their
 * email, else their truncated user id.
 *
 * Args:
 *   person: The person, or null for nobody.
 *   options: `readerId` to recognise the reader and `you`, the word for
 *     them; without both the reader is named like anyone else.
 *
 * Returns:
 *   The label, or null for someone the reader doesn't know (no id, no label).
 */
export function personLabel(
  person: PersonLike | null | undefined,
  options: { readerId?: string; you?: string } = {},
): string | null {
  if (!person) return null;
  if (options.you && isReader(person, options.readerId)) return options.you;
  const email = person.email?.trim();
  if (email) return email;
  const label = person.label?.trim();
  if (label && label !== person.user_id) return label;
  const id = person.user_id || label;
  return id ? truncateSub(id) : null;
}

/**
 * The reader's user id: the subject of their session token.
 *
 * Args:
 *   token: The session token, or null when signed out or auth is off.
 *
 * Returns:
 *   The `sub` claim, or undefined without one.
 */
export function readerIdFromToken(
  token: string | null | undefined,
): string | undefined {
  const payload = token ? decodeJwtPayload(token) : null;
  return typeof payload?.sub === 'string' ? payload.sub : undefined;
}
