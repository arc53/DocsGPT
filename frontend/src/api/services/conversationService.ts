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
  getSharedConversation: (identifier: string): Promise<any> =>
    apiClient.get(endpoints.CONVERSATION.SHARED_CONVERSATION(identifier)),
};

export default conversationService;
