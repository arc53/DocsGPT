export const baseURL =
  import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

// Request deduplication - prevent duplicate requests for the same URL
// This helps avoid redundant API calls when components make identical requests simultaneously
const pendingRequests = new Map<string, Promise<Response>>();

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

/**
 * Fetch with deduplication to prevent identical concurrent requests
 * @param url - The request URL
 * @param options - Fetch options
 * @returns Promise resolving to Response
 */
const fetchOnce = (url: string, options?: RequestInit): Promise<Response> => {
  // Create a cache key based on URL and method
  const cacheKey = `${options?.method || 'GET'}:${url}`;

  // For non-GET requests or requests with body, don't deduplicate
  if (options?.method && options.method !== 'GET' && options.body) {
    return fetch(url, options);
  }

  // If identical request is already pending, return that promise
  if (pendingRequests.has(cacheKey)) {
    return pendingRequests.get(cacheKey)!;
  }

  // Make the request and store the promise
  const requestPromise = fetch(url, options).finally(() => {
    // Clean up after request completes
    pendingRequests.delete(cacheKey);
  });

  pendingRequests.set(cacheKey, requestPromise);
  return requestPromise;
};

const apiClient = {
  get: (
    url: string,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<any> =>
    fetchOnce(`${baseURL}${url}`, {
      method: 'GET',
      headers: getHeaders(token, headers),
      signal,
    }).then((response) => {
      return response;
    }),

  post: (
    url: string,
    data: any,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<any> =>
    fetchOnce(`${baseURL}${url}`, {
      method: 'POST',
      headers: getHeaders(token, headers),
      body: JSON.stringify(data),
      signal,
    }).then((response) => {
      return response;
    }),

  postFormData: (
    url: string,
    formData: FormData,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<Response> => {
    return fetchOnce(`${baseURL}${url}`, {
      method: 'POST',
      headers: getHeaders(token, headers, true),
      body: formData,
      signal,
    });
  },

  put: (
    url: string,
    data: any,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<any> =>
    fetchOnce(`${baseURL}${url}`, {
      method: 'PUT',
      headers: getHeaders(token, headers),
      body: JSON.stringify(data),
      signal,
    }).then((response) => {
      return response;
    }),

  putFormData: (
    url: string,
    formData: FormData,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<Response> => {
    return fetchOnce(`${baseURL}${url}`, {
      method: 'PUT',
      headers: getHeaders(token, headers, true),
      body: formData,
      signal,
    });
  },

  delete: (
    url: string,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<any> =>
    fetchOnce(`${baseURL}${url}`, {
      method: 'DELETE',
      headers: getHeaders(token, headers),
      signal,
    }).then((response) => {
      return response;
    }),
};

export default apiClient;
