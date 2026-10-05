export type ConversationSummary = {
  id: string;
  name: string;
  agent_id: string | null;
  /** The list's sort key (ISO-8601), the cursor for the next page. */
  date?: string;
  match_field?: 'name' | 'prompt' | 'response' | null;
  match_snippet?: string | null;
  /** A message landed the user has not seen (a background job's follow-up). */
  unread?: boolean;
};

export type GetConversationsResult = {
  data: ConversationSummary[] | null;
  loading: boolean;
};
