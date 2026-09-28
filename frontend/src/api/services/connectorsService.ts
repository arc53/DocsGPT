import apiClient, { throttledApiClient } from '../client';
import endpoints from '../endpoints';

// apiClient resolves to the raw fetch Response; parse it here so the slice and
// components get plain data. A non-2xx body still parses (``success: false``).
const json = async (response: Response) => {
  try {
    return await response.json();
  } catch {
    return { success: false };
  }
};

const connectorsService = {
  getCatalog: async (token: string | null) =>
    json(
      await throttledApiClient.get(endpoints.USER.CONNECTORS_CATALOG, token),
    ),
  listConnections: async (token: string | null) =>
    json(await throttledApiClient.get(endpoints.USER.CONNECTIONS, token)),
  getConnection: async (id: string, token: string | null) =>
    json(await apiClient.get(endpoints.USER.CONNECTION(id), token)),
  disconnect: async (id: string, token: string | null) =>
    json(
      await apiClient.post(endpoints.USER.CONNECTION_DISCONNECT(id), {}, token),
    ),
};

export default connectorsService;
