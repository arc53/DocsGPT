export type ConversationSummary = {
  id: string;
  name: string;
  agent_id: string | null;
  match_field?: 'name' | 'prompt' | 'response' | null;
  match_snippet?: string | null;
};

export type GetConversationsResult = {
  data: ConversationSummary[] | null;
  loading: boolean;
};
