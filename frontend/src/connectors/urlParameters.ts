import type { CredentialField } from './types';

/**
 * Whether `value` (trimmed) matches the whole of the field's pattern, as the
 * server checks it. A pattern the browser can't compile refuses every value:
 * the server decides, and it would refuse an unchecked one anyway.
 */
export const urlParameterValid = (
  field: Pick<CredentialField, 'pattern'>,
  value: string | undefined,
) => {
  const trimmed = (value ?? '').trim();
  if (!trimmed) return false;
  if (!field.pattern) return true;
  try {
    return new RegExp(`^(?:${field.pattern})$`).test(trimmed);
  } catch {
    return false;
  }
};

/**
 * Whether every URL parameter a preset needs (Supabase's project ref) has a
 * value its pattern accepts, so the sign-in can start.
 */
export const urlParametersValid = (
  fields: CredentialField[],
  values: Record<string, string>,
) => fields.every((field) => urlParameterValid(field, values[field.key]));

/** The preset's MCP URL carrying the values, as the connection is saved with. */
export const withUrlParameters = (
  url: string,
  fields: CredentialField[],
  values: Record<string, string>,
) => {
  if (!fields.length) return url;
  const parsed = new URL(url);
  fields.forEach((field) =>
    parsed.searchParams.set(field.key, (values[field.key] ?? '').trim()),
  );
  return parsed.toString();
};
