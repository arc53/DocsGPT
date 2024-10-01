const baseURL = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

const defaultHeaders = {
  'Content-Type': 'application/json',
};

const apiClient = {
  get: (url: string, headers = {}, signal?: AbortSignal): Promise<any> =>
    fetch(`${baseURL}${url}`, {
      method: 'GET',
      headers: {
        ...defaultHeaders,
        ...headers,
      },
      signal,
    }).then((response) => {
      return response;
    }),

  post: (
    url: string,
    data: any,
    headers = {},
    signal?: AbortSignal,
  ): Promise<any> =>
    fetch(`${baseURL}${url}`, {
      method: 'POST',
      headers: {
        ...defaultHeaders,
        ...headers,
      },
      body: JSON.stringify(data),
      signal,
    }).then((response) => {
      return response;
    }),

  put: (
    url: string,
    data: any,
    headers = {},
    signal?: AbortSignal,
  ): Promise<any> =>
    fetch(`${baseURL}${url}`, {
      method: 'PUT',
      headers: {
        ...defaultHeaders,
        ...headers,
      },
      body: JSON.stringify(data),
      signal,
    }).then((response) => {
      return response;
    }),

  delete: (url: string, headers = {}, signal?: AbortSignal): Promise<any> =>
    fetch(`${baseURL}${url}`, {
      method: 'DELETE',
      headers: {
        ...defaultHeaders,
        ...headers,
      },
      signal,
    }).then((response) => {
      return response;
    }),
};

export default apiClient;
