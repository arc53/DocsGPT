/**
 * Guards for reading a server payload defensively: a reader keeps a value
 * only when it has the shape it expects and drops the rest.
 */

export const isString = (value: unknown): value is string =>
  typeof value === 'string';

/** A finite number of zero or more. */
export const isCount = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0;

/** A plain object: not null, not an array. */
export const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const UUID_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * A UUID, the shape the server's ids take (a conversation, a message, a
 * resource in `resource_filter`); a built-in id like `default` is not one.
 */
export const isUuid = (value: unknown): value is string =>
  typeof value === 'string' && UUID_REGEX.test(value);

/** The value as a plain object, or null when it isn't one. */
export const asRecord = (value: unknown): Record<string, unknown> | null =>
  isRecord(value) ? value : null;
