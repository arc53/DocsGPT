/**
 * Whether a window message is the OAuth result posted by the connector popup we opened.
 * `expectedOrigin` is the callback origin reported by the backend, when known.
 */
export const isTrustedConnectorMessage = (
  event: Pick<MessageEvent, 'origin' | 'source'>,
  authWindow: Window | null,
  expectedOrigin?: string | null,
): boolean => {
  if (!authWindow || event.source !== authWindow) return false;
  return !expectedOrigin || event.origin === expectedOrigin;
};
