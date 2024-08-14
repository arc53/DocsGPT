export type MESSAGE_TYPE = 'QUESTION' | 'ANSWER' | 'ERROR';
export type Status = 'idle' | 'loading' | 'failed';
export type FEEDBACK = 'LIKE' | 'DISLIKE';

export interface Message {
  text: string;
  type: MESSAGE_TYPE;
}

export interface ConversationState {
  queries: Query[];
  status: Status;
  conversationId: string | null;
}

export interface Answer {
  answer: string;
  query: string;
  result: string;
  sources: { title: string; text: string; source: string }[];
  conversationId: string | null;
  title: string | null;
}

export interface Query {
  prompt: string;
  response?: string;
  feedback?: FEEDBACK;
  error?: string;
  sources?: { title: string; text: string; source: string }[];
  conversationId?: string | null;
  title?: string | null;
}
export interface RetrievalPayload {
  question: string;
  active_docs?: string;
  retriever?: string;
  history: string;
  conversation_id: string | null;
  prompt_id?: string | null;
  chunks: string;
  token_limit: number;
}
