import { ToolCallsType } from './types';

export type MESSAGE_TYPE = 'QUESTION' | 'ANSWER' | 'ERROR';
export type Status = 'idle' | 'loading' | 'failed' | 'awaiting_tool_actions';
export type FEEDBACK = 'LIKE' | 'DISLIKE' | null;
// Mirrors ``conversation_messages.status``.
export type MessageStatus = 'pending' | 'streaming' | 'complete' | 'failed';

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

export interface ResearchStep {
  query: string;
  rationale?: string;
  status: 'pending' | 'researching' | 'complete';
}

export interface ResearchState {
  plan?: ResearchStep[];
  complexity?: string;
  status?: string;
  elapsed_seconds?: number;
  tokens_used?: number;
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
  structured?: boolean;
  schema?: object;
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
  // Set when this answer came from a workflow agent run; lets the chat render
  // the run's produced artifacts via WorkflowRunArtifacts.
  workflow_run_id?: string;
  error?: string;
  // Non-fatal notice (e.g. some workflow input documents were dropped). Shown
  // alongside the answer; unlike ``error`` it does not fail the turn or end the stream.
  notice?: string;
  attachments?: { id: string; fileName: string }[];
  structured?: boolean;
  schema?: object;
  research?: ResearchState;
  // WAL placeholder id; lets the client tail an in-flight stream.
  messageId?: string;
  messageStatus?: MessageStatus;
  requestId?: string;
  lastHeartbeatAt?: string;
  // Persisted so Retry can re-send the same key for server-side dedup.
  idempotencyKey?: string;
}

export interface RetrievalPayload {
  question: string;
  active_docs?: string | string[];
  retriever?: string;
  conversation_id: string | null;
  prompt_id?: string | null;
  chunks: string;
  isNoneDoc: boolean;
  index?: number;
  agent_id?: string;
  attachments?: string[];
  save_conversation?: boolean;
  visibility?: 'listed' | 'hidden';
  model_id?: string;
}
