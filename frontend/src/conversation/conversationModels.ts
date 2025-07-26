import { ToolCallsType } from './types';

export type MESSAGE_TYPE = 'QUESTION' | 'ANSWER' | 'ERROR';
export type Status = 'idle' | 'loading' | 'failed';
export type FEEDBACK = 'LIKE' | 'DISLIKE' | null;

export interface Message {
  text: string;
  type: MESSAGE_TYPE;
}

export interface Attachment {
  id?: string;
  fileName: string;
  status: 'uploading' | 'processing' | 'completed' | 'failed';
  progress: number;
  taskId?: string;
  token_count?: number;
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
  conversationId: string | null;
  title: string | null;
  thought: string;
  sources: { title: string; text: string; source: string }[];
  tool_calls: ToolCallsType[];
}

export interface Query {
  prompt: string;
  response?: string;
  feedback?: FEEDBACK;
  conversationId?: string | null;
  title?: string | null;
  thought?: string;
  sources?: { title: string; text: string; link: string }[];
  tool_calls?: ToolCallsType[];
  error?: string;
  attachments?: { id: string; fileName: string }[];
}

export interface RetrievalPayload {
  question: string;
  active_docs?: string;
  retriever?: string;
  conversation_id: string | null;
  prompt_id?: string | null;
  chunks: string;
  token_limit: number;
  isNoneDoc: boolean;
  index?: number;
  agent_id?: string;
  attachments?: string[];
  save_conversation?: boolean;
}
