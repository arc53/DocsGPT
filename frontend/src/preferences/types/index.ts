export type ConversationSummary = {
  id: string;
  name: string;
  agent_id: string | null;
  /** The list's sort key (ISO-8601), the cursor for the next page. */
  date?: string;
  match_field?: 'name' | 'prompt' | 'response' | null;
  match_snippet?: string | null;
};

export type GetConversationsResult = {
  data: ConversationSummary[] | null;
  loading: boolean;
};
