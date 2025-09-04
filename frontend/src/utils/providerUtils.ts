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