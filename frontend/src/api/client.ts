import { throttle } from 'lodash';

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

// Throttled post function with 500ms delay
const throttledPost = throttle(
  (
    url: string,
    data: any,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<any> =>
    fetch(`${baseURL}${url}`, {
      method: 'POST',
      headers: getHeaders(token, headers),
      body: JSON.stringify(data),
      signal,
    }).then((response) => {
      return response;
    }),
  500, // 500ms delay between calls
  { leading: true, trailing: false } // Only allow the first call in the window
);

const apiClient = {
  get: (
    url: string,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<any> =>
    fetch(`${baseURL}${url}`, {
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
  ): Promise<any> => throttledPost(url, data, token, headers, signal),

  postFormData: (
    url: string,
    formData: FormData,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<Response> => {
    return fetch(`${baseURL}${url}`, {
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
    fetch(`${baseURL}${url}`, {
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
    return fetch(`${baseURL}${url}`, {
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
    fetch(`${baseURL}${url}`, {
      method: 'DELETE',
      headers: getHeaders(token, headers),
      signal,
    }).then((response) => {
      return response;
    }),
};

export default apiClient;