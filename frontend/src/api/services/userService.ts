import apiClient from '../client';
import endpoints from '../endpoints';

const userService = {
  getDocs: (): Promise<any> => apiClient.get(`${endpoints.USER.DOCS}`),
  getDocsWithPagination: (query: string): Promise<any> =>
    apiClient.get(`${endpoints.USER.DOCS_PAGINATED}?${query}`),
  checkDocs: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.DOCS_CHECK, data),
  getAPIKeys: (): Promise<any> => apiClient.get(endpoints.USER.API_KEYS),
  createAPIKey: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.CREATE_API_KEY, data),
  deleteAPIKey: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.DELETE_API_KEY, data),
  getPrompts: (): Promise<any> => apiClient.get(endpoints.USER.PROMPTS),
  createPrompt: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.CREATE_PROMPT, data),
  deletePrompt: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.DELETE_PROMPT, data),
  updatePrompt: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.UPDATE_PROMPT, data),
  getSinglePrompt: (id: string): Promise<any> =>
    apiClient.get(endpoints.USER.SINGLE_PROMPT(id)),
  deletePath: (docPath: string): Promise<any> =>
    apiClient.get(endpoints.USER.DELETE_PATH(docPath)),
  getTaskStatus: (task_id: string): Promise<any> =>
    apiClient.get(endpoints.USER.TASK_STATUS(task_id)),
  getMessageAnalytics: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.MESSAGE_ANALYTICS, data),
  getTokenAnalytics: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.TOKEN_ANALYTICS, data),
  getFeedbackAnalytics: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.FEEDBACK_ANALYTICS, data),
  getLogs: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.LOGS, data),
  manageSync: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.MANAGE_SYNC, data),
  getAvailableTools: (): Promise<any> =>
    apiClient.get(endpoints.USER.GET_AVAILABLE_TOOLS),
  getUserTools: (): Promise<any> =>
    apiClient.get(endpoints.USER.GET_USER_TOOLS),
  createTool: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.CREATE_TOOL, data),
  updateToolStatus: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.UPDATE_TOOL_STATUS, data),
  updateTool: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.UPDATE_TOOL, data),
  deleteTool: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.DELETE_TOOL, data),
  getDocumentChunks: (
    docId: string,
    page: number,
    perPage: number,
  ): Promise<any> =>
    apiClient.get(endpoints.USER.GET_CHUNKS(docId, page, perPage)),
  addChunk: (data: any): Promise<any> =>
    apiClient.post(endpoints.USER.ADD_CHUNK, data),
  deleteChunk: (docId: string, chunkId: string): Promise<any> =>
    apiClient.delete(endpoints.USER.DELETE_CHUNK(docId, chunkId)),
};

export default userService;
