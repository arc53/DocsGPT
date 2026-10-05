type MethodBadgeVariant =
  'default' | 'neutral' | 'success' | 'warning' | 'destructive' | 'info';

// Reads, writes, replaces and deletes take the status tokens that match
// their weight; PATCH is the brand tint, and the rest are neutral.
const METHOD_VARIANTS: Record<string, MethodBadgeVariant> = {
  GET: 'success',
  POST: 'info',
  PUT: 'warning',
  DELETE: 'destructive',
  PATCH: 'default',
  HEAD: 'neutral',
  OPTIONS: 'neutral',
};

/**
 * The `Badge` variant for an HTTP method pill.
 *
 * @param method - The HTTP method, in any case.
 * @returns The variant for `<Badge>`; `neutral` for an unknown method.
 */
export function getMethodBadgeVariant(method: string): MethodBadgeVariant {
  return METHOD_VARIANTS[method.toUpperCase()] ?? 'neutral';
}
