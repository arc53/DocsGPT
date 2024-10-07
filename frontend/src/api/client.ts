const baseURL = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

const defaultHeaders = {
  'Content-Type': 'application/json',
};

type RequestParams = {
  resolve: (value?: any) => void;
  reject: (reason?: any) => void;
  request: () => Promise<any>;
};

class ThrottledApiClient {
  limit: number; // Maximum number of requests allowed in the interval
  interval: number; // Time interval in milliseconds
  queue: RequestParams[]; // Queue to store requests
  isThrottling: boolean; // Flag to check if we are currently throttling
  requestCount: number; // Count of requests sent in the current interval

  constructor(limit: number, interval: number) {
    this.limit = limit; // Max requests
    this.interval = interval; // Interval in ms
    this.queue = []; // Queue to store requests
    this.isThrottling = false; // Flag to check if we are currently throttling
    this.requestCount = 0; // Initialize request count
  }

  processQueue() {
    if (this.queue.length === 0 || this.isThrottling) return;

    if (this.requestCount >= this.limit) {
      // If limit is reached, wait for the next interval
      setTimeout(() => {
        this.requestCount = 0; // Reset count after the interval
        this.processQueue(); // Process the next request in the queue
      }, this.interval);
      return;
    }

    this.isThrottling = true;
    const { resolve, reject, request } = this.queue.shift()!;

    // Increment request count
    this.requestCount++;

    request()
      .then(resolve)
      .catch(reject)
      .finally(() => {
        this.isThrottling = false;
        this.processQueue(); // Process the next request in the queue
      });
  }

  request(
    method: string,
    url: string,
    data: any = null,
    headers: HeadersInit = {},
    signal?: AbortSignal,
  ) {
    return new Promise<any>((resolve, reject) => {
      const request = () =>
        fetch(`${baseURL}${url}`, {
          method,
          headers: {
            ...defaultHeaders,
            ...headers,
          },
          body: data ? JSON.stringify(data) : undefined,
          signal,
        }).then((response) => response);

      this.queue.push({ resolve, reject, request });
      this.processQueue();
    });
  }

  get(url: string, headers: HeadersInit = {}, signal?: AbortSignal) {
    return this.request('GET', url, null, headers, signal);
  }

  post(
    url: string,
    data: any,
    headers: HeadersInit = {},
    signal?: AbortSignal,
  ) {
    return this.request('POST', url, data, headers, signal);
  }

  put(url: string, data: any, headers: HeadersInit = {}, signal?: AbortSignal) {
    return this.request('PUT', url, data, headers, signal);
  }

  delete(url: string, headers: HeadersInit = {}, signal?: AbortSignal) {
    return this.request('DELETE', url, null, headers, signal);
  }
}

const apiClient = new ThrottledApiClient(5, 5000); // Allow 5 requests every 2000ms (2 seconds)
export default apiClient;
