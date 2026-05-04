// Per-user-action key for the ``Idempotency-Key`` header. Server
// scopes by user, so cross-user reuse is harmless.
export function newIdempotencyKey(): string {
  if (
    typeof crypto !== 'undefined' &&
    typeof crypto.randomUUID === 'function'
  ) {
    return crypto.randomUUID();
  }
  // Fallback for older Safari / jsdom; uniqueness is enough.
  const rand = () => Math.random().toString(16).slice(2, 10);
  return `${rand()}-${rand()}-${rand()}-${rand()}`;
}
