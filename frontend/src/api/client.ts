import { withThrottle, type FetchLike } from './throttle';

export const baseURL =
  import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

const getHeaders = (
  token: string | null,
  customHeaders = {},
  isFormData = false,
): HeadersInit => {
  const headers: HeadersInit = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...customHeaders,
  };

  if (!isFormData) {
    headers['Content-Type'] = 'application/json';
  }

  return headers;
};

const createClient = (transport: FetchLike) => {
  const request = (url: string, init: RequestInit): Promise<Response> =>
    transport(`${baseURL}${url}`, init);

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
      headers = {},
      signal?: AbortSignal,
    ): Promise<any> =>
      request(url, {
        method: 'DELETE',
        headers: getHeaders(token, headers),
        signal,
      }),
  };
};

const apiClient = createClient((url, init) => fetch(url, init));

// Throttled client for endpoints that fan out, are polled, or are commonly
// requested concurrently from multiple components. Shares a single concurrency
// budget and de-duplicates identical in-flight GETs.
export const throttledApiClient = createClient(
  withThrottle((url, init) => fetch(url, init), { debugLabel: 'api' }),
);

if (import.meta.env.DEV && typeof window !== 'undefined') {
  (window as unknown as Record<string, unknown>).__apiClient = apiClient;
  (window as unknown as Record<string, unknown>).__throttledApiClient =
    throttledApiClient;
  (window as unknown as Record<string, unknown>).__baseURL = baseURL;
}

export default apiClient;
