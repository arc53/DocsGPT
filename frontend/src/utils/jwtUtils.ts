export function decodeJwtPayload(
  token: string,
): Record<string, unknown> | null {
  try {
    const segment = token.split('.')[1];
    if (!segment) return null;
    const base64 = segment.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64.padEnd(
      base64.length + ((4 - (base64.length % 4)) % 4),
      '=',
    );
    return JSON.parse(atob(padded));
  } catch {
    return null;
  }
}

export function isJwtExpired(token: string, skewMs = 30000): boolean {
  const exp = decodeJwtPayload(token)?.exp;
  // Tokens without an exp claim (simple_jwt / session_jwt) never expire.
  if (typeof exp !== 'number') return false;
  return exp * 1000 <= Date.now() + skewMs;
}

export function getJwtRemainingMs(token: string): number | null {
  const exp = decodeJwtPayload(token)?.exp;
  if (typeof exp !== 'number') return null;
  return exp * 1000 - Date.now();
}
