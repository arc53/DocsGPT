export type NodeType =
  'start' | 'end' | 'agent' | 'note' | 'state' | 'condition' | 'code' | 'loop';

/** Which failures a node retries: upstream errors, or an unusable reply. */
export type RetryOn = 'transient' | 'invalid_output';

/**
 * How a node retries a failed attempt; unset fields fall back to the
 * workflow's ``retry_defaults``, then to the built-in defaults.
 */
export interface RetryConfig {
  /** 1 to 5, counting the first try; 1 never retries. */
  max_attempts?: number;
  /** Seconds before retry n: entry n - 1, or the last one past the end. */
  backoff_seconds?: number[];
  on?: RetryOn[];
}

/** An agent node's config; only the fields read by type are listed. */
export interface AgentNodeConfig {
  output_variable?: string;
  json_schema?: Record<string, unknown>;
  retry?: RetryConfig;
  [key: string]: unknown;
}

/** A loop node: runs the nodes inside it once per item of a state list. */
export interface LoopNodeConfig {
  items: string;
  item_variable: string;
  concurrency: number;
  max_items: number;
  on_item_error: 'fail' | 'skip' | 'collect';
  output_variable?: string;
  result_variable?: string;
}

export interface CodeNodeConfig {
  code: string;
  inputs: string[];
  output_variable?: string;
  timeout?: number;
  json_schema?: Record<string, unknown>;
  retry?: RetryConfig;
}

export interface ConditionCase {
  name?: string;
  expression: string;
  sourceHandle: string;
}

export interface ConditionNodeConfig {
  mode: 'simple' | 'advanced';
  cases: ConditionCase[];
}

export interface StateOperationConfig {
  expression: string;
  target_variable: string;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
}

export interface WorkflowNode {
  id: string;
  type: NodeType;
  title: string;
  description?: string;
  position: { x: number; y: number };
  data: Record<string, any>;
}

export interface WorkflowDefinition {
  id?: string;
  name: string;
  retry_defaults?: RetryConfig | null;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  created_at?: string;
  updated_at?: string;
}

export type ExecutionStatus = 'pending' | 'running' | 'completed' | 'failed';

/** One try of a node that ran more than once. */
export interface NodeAttemptLog {
  attempt: number;
  status: 'completed' | 'failed';
  started_at: string;
  completed_at: string;
  duration_ms: number;
  error?: string | null;
  reason?: RetryOn | null;
}

export interface NodeExecutionLog {
  node_id: string;
  status: ExecutionStatus;
  input_state: Record<string, any>;
  output_state: Record<string, any>;
  error?: string;
  started_at: number;
  completed_at?: number;
  logs: string[];
  /** Each try, when the node ran more than once; empty otherwise. */
  attempts?: NodeAttemptLog[];
}

export interface WorkflowRun {
  workflow_id: string;
  status: ExecutionStatus;
  state: Record<string, any>;
  node_logs: NodeExecutionLog[];
  created_at: number;
  completed_at?: number;
}
