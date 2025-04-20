export type ConversationSummary = {
  id: string;
  name: string;
  agent_id: string | null;
};

export type GetConversationsResult = {
  data: ConversationSummary[] | null;
  loading: boolean;
};
