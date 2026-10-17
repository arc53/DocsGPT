/**
 * Connector sign-ins used to keep a random session handle per provider in
 * localStorage (``<provider>_session_token``). Credentials now live only on
 * the server and the browser refers to a connection by its id, so the old
 * handles are claimed once (linked to the signed-in user's connection) and
 * removed.
 */

import connectorsService from '../api/services/connectorsService';

const LEGACY_PROVIDERS = ['google_drive', 'share_point', 'confluence'];

const legacyKey = (provider: string) => `${provider}_session_token`;

export const claimLegacySessionTokens = async (
  token: string | null,
): Promise<void> => {
  for (const provider of LEGACY_PROVIDERS) {
    let value: string | null = null;
    try {
      value = localStorage.getItem(legacyKey(provider));
    } catch {
      return;
    }
    if (!value) continue;
    try {
      await connectorsService.claim(provider, value, token);
    } catch {
      // The handle is useless to this frontend either way; drop it.
    } finally {
      localStorage.removeItem(legacyKey(provider));
    }
  }
};
