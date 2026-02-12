export type NodeType = 'start' | 'end' | 'agent' | 'note' | 'state';

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
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  created_at?: string;
  updated_at?: string;
}

export type ExecutionStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface NodeExecutionLog {
  node_id: string;
  status: ExecutionStatus;
  input_state: Record<string, any>;
  output_state: Record<string, any>;
  error?: string;
  started_at: number;
  completed_at?: number;
  logs: string[];
}

export interface WorkflowRun {
  workflow_id: string;
  status: ExecutionStatus;
  state: Record<string, any>;
  node_logs: NodeExecutionLog[];
  created_at: number;
  completed_at?: number;
}
