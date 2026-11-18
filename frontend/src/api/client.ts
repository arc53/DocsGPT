import { envVar } from '@/env';
import {
  reportWorkspaceRefusal,
  requestWorkspace,
  WORKSPACE_HEADER,
} from '../workspace/requestWorkspace';
import { withThrottle, type FetchLike } from './throttle';

export const baseURL = envVar('VITE_API_HOST') || 'https://docsapi.arc53.com';

// The workspace goes on every request, Personal included, before the caller's
// own headers so a call can name another one.
const getHeaders = (
  token: string | null,
  customHeaders = {},
  isFormData = false,
): HeadersInit => {
  const headers: HeadersInit = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    [WORKSPACE_HEADER]: requestWorkspace(),
    ...customHeaders,
  };

  if (!isFormData) {
    headers['Content-Type'] = 'application/json';
  }

  return headers;
};

/** The workspace a request was sent for, read from its headers. */
const sentWorkspace = (init?: RequestInit): string => {
  const headers = init?.headers as Record<string, string> | undefined;
  return headers?.[WORKSPACE_HEADER] ?? '';
};

/**
 * Reads a refusal's code from a copy of the body, without holding up the
 * caller, which still reads the response itself.
 */
const watchWorkspaceRefusal = (response: Response, workspace: string) => {
  if (response?.status !== 404 && response?.status !== 403) return;
  if (typeof response.clone !== 'function') return;
  response
    .clone()
    .json()
    .then((body) =>
      reportWorkspaceRefusal(response.status, body?.error, workspace),
    )
    .catch(() => undefined);
};

const createClient = (transport: FetchLike) => {
  const request = async (url: string, init: RequestInit): Promise<Response> => {
    const response = await transport(`${baseURL}${url}`, init);
    watchWorkspaceRefusal(response, sentWorkspace(init));
    return response;
  };

  return {
    get: (
      url: string,
      token: string | null,
      headers = {},
      signal?: AbortSignal,
    ): Promise<any> =>
      request(url, {
        method: 'GET',
        headers: getHeaders(token, headers),
        signal,
      }),

    post: (
      url: string,
      data: any,
      token: string | null,
      headers = {},
      signal?: AbortSignal,
    ): Promise<any> =>
      request(url, {
        method: 'POST',
        headers: getHeaders(token, headers),
        body: JSON.stringify(data),
        signal,
      }),

    postFormData: (
      url: string,
      formData: FormData,
      token: string | null,
      headers = {},
      signal?: AbortSignal,
    ): Promise<Response> =>
      request(url, {
        method: 'POST',
        headers: getHeaders(token, headers, true),
        body: formData,
        signal,
      }),

    put: (
      url: string,
      data: any,
      token: string | null,
      headers = {},
      signal?: AbortSignal,
    ): Promise<any> =>
      request(url, {
        method: 'PUT',
        headers: getHeaders(token, headers),
        body: JSON.stringify(data),
        signal,
      }),

    patch: (
      url: string,
      data: any,
      token: string | null,
      headers = {},
      signal?: AbortSignal,
    ): Promise<any> =>
      request(url, {
        method: 'PATCH',
        headers: getHeaders(token, headers),
        body: JSON.stringify(data),
        signal,
      }),

    putFormData: (
      url: string,
      formData: FormData,
      token: string | null,
      headers = {},
      signal?: AbortSignal,
    ): Promise<Response> =>
      request(url, {
        method: 'PUT',
        headers: getHeaders(token, headers, true),
        body: formData,
        signal,
      }),

    delete: (
      url: string,
      token: string | null,
      data?: any,
      headers = {},
      signal?: AbortSignal,
    ): Promise<any> =>
      request(url, {
        method: 'DELETE',
        headers: getHeaders(token, headers),
        body: data !== undefined ? JSON.stringify(data) : undefined,
        signal,
      }),
  };
};

const apiClient = createClient((url, init) => fetch(url, init));

// Throttled client for endpoints that fan out, are polled, or are commonly
// requested concurrently from multiple components. Shares a single concurrency
// budget and de-duplicates identical in-flight GETs.
// The workspace is part of the dedupe key: a Personal and a team request for
// the same URL are different lists.
export const throttledApiClient = createClient(
  withThrottle((url, init) => fetch(url, init), {
    debugLabel: 'api',
    dedupeKey: (url, init) => `GET ${url} ${sentWorkspace(init)}`,
  }),
);

if (import.meta.env.DEV && typeof window !== 'undefined') {
  (window as unknown as Record<string, unknown>).__apiClient = apiClient;
  (window as unknown as Record<string, unknown>).__throttledApiClient =
    throttledApiClient;
  (window as unknown as Record<string, unknown>).__baseURL = baseURL;
}

export default apiClient;
