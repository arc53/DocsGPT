import apiClient from '../client';
import endpoints from '../endpoints';

const userService = {
  getDocs: (): Promise<any> => apiClient.get(endpoints.USER.DOCS),
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
};

export default userService;
