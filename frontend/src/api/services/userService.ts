import apiClient from '../client';
import endpoints from '../endpoints';

const userService = {
  getConfig: (): Promise<any> => apiClient.get(endpoints.USER.CONFIG, null),
  getNewToken: (): Promise<any> =>
    apiClient.get(endpoints.USER.NEW_TOKEN, null),
  getDocs: (token: string | null): Promise<any> =>
    apiClient.get(`${endpoints.USER.DOCS}`, token),
  getDocsWithPagination: (query: string, token: string | null): Promise<any> =>
    apiClient.get(`${endpoints.USER.DOCS_PAGINATED}?${query}`, token),
  checkDocs: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.DOCS_CHECK, data, token),
  getAPIKeys: (token: string | null): Promise<any> =>
    apiClient.get(endpoints.USER.API_KEYS, token),
  createAPIKey: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.CREATE_API_KEY, data, token),
  deleteAPIKey: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.DELETE_API_KEY, data, token),
  getPrompts: (token: string | null): Promise<any> =>
    apiClient.get(endpoints.USER.PROMPTS, token),
  createPrompt: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.CREATE_PROMPT, data, token),
  deletePrompt: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.DELETE_PROMPT, data, token),
  updatePrompt: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.UPDATE_PROMPT, data, token),
  getSinglePrompt: (id: string, token: string | null): Promise<any> =>
    apiClient.get(endpoints.USER.SINGLE_PROMPT(id), token),
  getProxies: (token: string | null): Promise<any> =>
    apiClient.get(endpoints.USER.PROXIES, token),
  createProxy: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.CREATE_PROXY, data, token),
  deleteProxy: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.DELETE_PROXY, data, token),
  updateProxy: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.UPDATE_PROXY, data, token),
  getSingleProxy: (id: string, token: string | null): Promise<any> =>
    apiClient.get(endpoints.USER.SINGLE_PROXY(id), token),
  deletePath: (docPath: string, token: string | null): Promise<any> =>
    apiClient.get(endpoints.USER.DELETE_PATH(docPath), token),
  getTaskStatus: (task_id: string, token: string | null): Promise<any> =>
    apiClient.get(endpoints.USER.TASK_STATUS(task_id), token),
  getMessageAnalytics: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.MESSAGE_ANALYTICS, data, token),
  getTokenAnalytics: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.TOKEN_ANALYTICS, data, token),
  getFeedbackAnalytics: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.FEEDBACK_ANALYTICS, data, token),
  getLogs: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.LOGS, data, token),
  manageSync: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.MANAGE_SYNC, data, token),
  getAvailableTools: (token: string | null): Promise<any> =>
    apiClient.get(endpoints.USER.GET_AVAILABLE_TOOLS, token),
  getUserTools: (token: string | null): Promise<any> =>
    apiClient.get(endpoints.USER.GET_USER_TOOLS, token),
  createTool: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.CREATE_TOOL, data, token),
  updateToolStatus: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.UPDATE_TOOL_STATUS, data, token),
  updateTool: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.UPDATE_TOOL, data, token),
  deleteTool: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.DELETE_TOOL, data, token),
  getDocumentChunks: (
    docId: string,
    page: number,
    perPage: number,
    token: string | null,
  ): Promise<any> =>
    apiClient.get(endpoints.USER.GET_CHUNKS(docId, page, perPage), token),
  addChunk: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.USER.ADD_CHUNK, data, token),
  deleteChunk: (
    docId: string,
    chunkId: string,
    token: string | null,
  ): Promise<any> =>
    apiClient.delete(endpoints.USER.DELETE_CHUNK(docId, chunkId), token),
  updateChunk: (data: any, token: string | null): Promise<any> =>
    apiClient.put(endpoints.USER.UPDATE_CHUNK, data, token),
};

export default userService;
