import type { AnswerSource } from './chatCompanion';
import { AnswerSegment } from './answerSegments';
import { ToolCallsType } from './types';

// Backend placeholder for a producer that ended before writing an answer.
export const TERMINATED_RESPONSE_PLACEHOLDER =
  'Response was terminated prior to completion, try regenerating.';

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
  sources: AnswerSource[];
  tool_calls: ToolCallsType[];
  structured?: boolean;
  schema?: object;
}

export interface WorkflowStep {
  nodeId: string;
  nodeType: string;
  title: string;
  status: 'running' | 'completed' | 'failed';
  /** Client clock, in ms, for the elapsed and duration labels. */
  startedAt?: number;
  endedAt?: number;
  /** One line about what the step did: its output, or the values it set. */
  detail?: string;
  error?: string;
}

export interface WorkflowProgress {
  steps: WorkflowStep[];
  /** How many steps the run takes; absent when a branch decides it. */
  total?: number;
}

export interface Query {
  prompt: string;
  response?: string;
  feedback?: FEEDBACK;
  conversationId?: string | null;
  title?: string | null;
  thought?: string;
  sources?: AnswerSource[];
  tool_calls?: ToolCallsType[];
  // Arrival-ordered layout of the fields above, so answer text, reasoning and
  // tool calls render where they happened. Recorded live, and rebuilt on load
  // from the order the backend saved (``hydrateSegments``); when that is absent
  // or no longer fits, ``getAnswerSegments`` synthesizes one.
  segments?: AnswerSegment[];
  // Set when this answer came from a workflow agent run; lets the chat render
  // the run's produced artifacts as cards (useRunArtifacts).
  workflow_run_id?: string;
  error?: string;
  // Why the turn failed, when the backend says (``context_length_exceeded``);
  // its presence also marks ``error`` as curated text rather than a raw error.
  errorCode?: string;
  // The values a curated error was worded from (``needed_tokens``…), so the
  // chat can word it in the user's language.
  errorParams?: Record<string, unknown>;
  // Non-fatal notice (e.g. some workflow input documents were dropped). Shown
  // alongside the answer; unlike ``error`` it does not fail the turn or end the stream.
  notice?: string;
  attachments?: { id: string; fileName: string }[];
  // Set once a failed turn's files were turned into Knowledge: a retry or an
  // edit then asks through the selected Knowledge, without the files.
  attachmentsInKnowledge?: boolean;
  structured?: boolean;
  schema?: object;
  research?: ResearchState;
  // A workflow agent's steps as they run, so the chat can show which one is
  // working; see ``workflowProgress``.
  workflow?: WorkflowProgress;
  // WAL placeholder id; lets the client tail an in-flight stream.
  messageId?: string;
  messageStatus?: MessageStatus;
  requestId?: string;
  lastHeartbeatAt?: string;
  // Persisted so Retry can re-send the same key for server-side dedup.
  idempotencyKey?: string;
  // Set on a continuation turn: its prompt is the background event that woke
  // the agent, shown as a system row instead of a user bubble.
  wake?: {
    source: string;
    count: number;
    /** Each event as a person reads it (label, status, short detail). */
    events?: { label?: string; status?: string; detail?: string }[];
  };
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
