import { ToolCallsType } from './types';

export type MESSAGE_TYPE = 'QUESTION' | 'ANSWER' | 'ERROR';
export type Status = 'idle' | 'loading' | 'failed';
export type FEEDBACK = 'LIKE' | 'DISLIKE' | null;

export interface Message {
  text: string;
  type: MESSAGE_TYPE;
}

export interface ConversationState {
  queries: Query[];
  status: Status;
  conversationId: string | null;
  attachments?: { fileName: string; id: string }[];
}

export interface Answer {
  answer: string;
  query: string;
  result: string;
  conversationId: string | null;
  title: string | null;
  sources: { title: string; text: string; source: string }[];
  tool_calls: ToolCallsType[];
}

export interface Query {
  prompt: string;
  response?: string;
  feedback?: FEEDBACK;
  conversationId?: string | null;
  title?: string | null;
  sources?: { title: string; text: string; source: string }[];
  tool_calls?: ToolCallsType[];
  error?: string;
  attachments?: { fileName: string; id: string }[];
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
  isNoneDoc: boolean;
  index?: number;
  attachments?: string[];
}
