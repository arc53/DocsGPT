import apiClient from '../client';
import endpoints from '../endpoints';

const conversationService = {
  answer: (
    data: any,
    token: string | null,
    signal: AbortSignal,
    headers: Record<string, string> = {},
  ): Promise<any> =>
    apiClient.post(endpoints.CONVERSATION.ANSWER, data, token, headers, signal),
  answerStream: (
    data: any,
    token: string | null,
    signal: AbortSignal,
    headers: Record<string, string> = {},
  ): Promise<any> =>
    apiClient.post(
      endpoints.CONVERSATION.ANSWER_STREAMING,
      data,
      token,
      headers,
      signal,
    ),
  search: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.CONVERSATION.SEARCH, data, token, {}),
  feedback: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.CONVERSATION.FEEDBACK, data, token, {}),
  getConversation: (id: string, token: string | null): Promise<any> =>
    apiClient.get(endpoints.CONVERSATION.CONVERSATION(id), token, {}),
  tailMessage: (messageId: string, token: string | null): Promise<any> =>
    apiClient.get(endpoints.CONVERSATION.MESSAGE_TAIL(messageId), token, {}),
  getConversations: (token: string | null): Promise<any> =>
    apiClient.get(endpoints.CONVERSATION.CONVERSATIONS, token, {}),
  searchConversations: (
    query: string,
    token: string | null,
    limit = 30,
  ): Promise<any> =>
    apiClient.get(
      endpoints.CONVERSATION.SEARCH_CONVERSATIONS(query, limit),
      token,
      {},
    ),
  shareConversation: (
    isPromptable: boolean,
    data: any,
    token: string | null,
  ): Promise<any> =>
    apiClient.post(
      endpoints.CONVERSATION.SHARE_CONVERSATION(isPromptable),
      data,
      token,
      {},
    ),
  getSharedConversation: (
    identifier: string,
    token: string | null,
  ): Promise<any> =>
    apiClient.get(
      endpoints.CONVERSATION.SHARED_CONVERSATION(identifier),
      token,
      {},
    ),
  delete: (id: string, data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.CONVERSATION.DELETE(id), data, token, {}),
  deleteAll: (token: string | null): Promise<any> =>
    apiClient.get(endpoints.CONVERSATION.DELETE_ALL, token, {}),
  update: (data: any, token: string | null): Promise<any> =>
    apiClient.post(endpoints.CONVERSATION.UPDATE, data, token, {}),
  chatCompletions: (
    data: any,
    agentApiKey: string,
    signal: AbortSignal,
  ): Promise<any> =>
    apiClient.post(
      endpoints.V1.CHAT_COMPLETIONS,
      data,
      null,
      { Authorization: `Bearer ${agentApiKey}` },
      signal,
    ),
};

export default conversationService;
