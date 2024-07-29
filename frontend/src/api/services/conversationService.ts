import apiClient from '../client';
import endpoints from '../endpoints';

const conversationService = {
  answer: (data: any, signal: AbortSignal): Promise<any> =>
    apiClient.post(endpoints.CONVERSATION.ANSWER, data, {}, signal),
  answerStream: (data: any, signal: AbortSignal): Promise<any> =>
    apiClient.post(endpoints.CONVERSATION.ANSWER_STREAMING, data, {}, signal),
  search: (data: any): Promise<any> =>
    apiClient.post(endpoints.CONVERSATION.SEARCH, data),
  feedback: (data: any): Promise<any> =>
    apiClient.post(endpoints.CONVERSATION.FEEDBACK, data),
  getConversation: (id: string): Promise<any> =>
    apiClient.get(endpoints.CONVERSATION.CONVERSATION(id)),
  getConversations: (): Promise<any> =>
    apiClient.get(endpoints.CONVERSATION.CONVERSATIONS),
  shareConversation: (isPromptable: boolean, data: any): Promise<any> =>
    apiClient.post(
      endpoints.CONVERSATION.SHARE_CONVERSATION(isPromptable),
      data,
    ),
  getSharedConversation: (identifier: string): Promise<any> =>
    apiClient.get(endpoints.CONVERSATION.SHARED_CONVERSATION(identifier)),
  delete: (id: string, data: any): Promise<any> =>
    apiClient.post(endpoints.CONVERSATION.DELETE(id), data),
  deleteAll: (data: any): Promise<any> =>
    apiClient.post(endpoints.CONVERSATION.DELETE_ALL, data),
  update: (data: any): Promise<any> =>
    apiClient.post(endpoints.CONVERSATION.UPDATE, data),
};

export default conversationService;
