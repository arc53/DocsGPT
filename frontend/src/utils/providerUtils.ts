/**
 * Utility functions for managing session tokens for different cloud service providers.
 * Follows the convention: {provider}_session_token
 */

export const getSessionToken = (provider: string): string | null => {
  return localStorage.getItem(`${provider}_session_token`);
};

export const setSessionToken = (provider: string, token: string): void => {
  localStorage.setItem(`${provider}_session_token`, token);
};

export const removeSessionToken = (provider: string): void => {
  localStorage.removeItem(`${provider}_session_token`);
};

export const validateProviderSession = async (
  token: string | null,
  provider: string,
) => {
  const apiHost = import.meta.env.VITE_API_HOST;
  return await fetch(`${apiHost}/api/connectors/validate-session`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      provider: provider,
      session_token: getSessionToken(provider),
    }),
  });
};
