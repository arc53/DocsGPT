export const baseURL =
  import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

const defaultHeaders = {
  'Content-Type': 'application/json',
};

const getHeaders = (token: string | null, customHeaders = {}): HeadersInit => {
  return {
    ...defaultHeaders,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...customHeaders,
  };
};

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
  ): Promise<any> =>
    fetch(`${baseURL}${url}`, {
      method: 'POST',
      headers: getHeaders(token, headers),
      body: JSON.stringify(data),
      signal,
    }).then((response) => {
      return response;
    }),

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
