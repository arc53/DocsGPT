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

// Replaces the debounce map. Stores active request controllers by URL.
const abortControllersMap: Map<string, AbortController> = new Map();

// Helper to catch 4xx/5xx HTTP errors and throw them properly
const handleResponse = (response: Response): Response => {
  if (!response.ok) {
    throw new Error(`HTTP Error: ${response.status} ${response.statusText}`);
  }
  return response;
};

const apiClient = {
  get: (
    url: string,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<Response> =>
    fetch(`${baseURL}${url}`, {
      method: 'GET',
      headers: getHeaders(token, headers),
      signal,
    }).then(handleResponse),
    
  post: (
    url: string,
    data: any,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<Response> => {
    if (!url) {
      return Promise.reject(new Error("Invalid URL"));
    }

    const fullUrl = `${baseURL}${url}`;

    // Cancel previous in-flight request to avoid duplicate chat calls
    const shouldCancelPrevious = ["/chat", "/stream"].some((endpoint) =>
      url.includes(endpoint)
    );

    let controller: AbortController | null = null;

    if (shouldCancelPrevious) {
      if (abortControllersMap.has(url)) {
        abortControllersMap.get(url)?.abort("Replaced by new request");
      }

      controller = new AbortController();
      abortControllersMap.set(url, controller);
    }

    const finalSignal = controller ? controller.signal : signal;

    const options: RequestInit = {
      method: "POST",
      headers: getHeaders(token, headers),
      body: JSON.stringify(data),
      signal: finalSignal,
    };

    return fetch(fullUrl, options)
      .then(handleResponse)
      .finally(() => {
        //FIX: Only delete if the map's current controller matches OUR controller
        if (shouldCancelPrevious && controller && abortControllersMap.get(url) === controller) {
          abortControllersMap.delete(url);
        }
      });
  },

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
    }).then(handleResponse);
  },

  put: (
    url: string,
    data: any,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<Response> =>
    fetch(`${baseURL}${url}`, {
      method: 'PUT',
      headers: getHeaders(token, headers),
      body: JSON.stringify(data),
      signal,
    }).then(handleResponse),

  patch: (
    url: string,
    data: any,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<Response> =>
    fetch(`${baseURL}${url}`, {
      method: 'PATCH',
      headers: getHeaders(token, headers),
      body: JSON.stringify(data),
      signal,
    }).then(handleResponse),

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
    }).then(handleResponse);
  },

  delete: (
    url: string,
    token: string | null,
    headers = {},
    signal?: AbortSignal,
  ): Promise<Response> =>
    fetch(`${baseURL}${url}`, {
      method: 'DELETE',
      headers: getHeaders(token, headers),
      signal,
    }).then(handleResponse),
};

export default apiClient;
