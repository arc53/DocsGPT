export type ToolCallsType = {
  tool_name: string;
  action_name: string;
  call_id: string;
  arguments: Record<string, any>;
  result?: Record<string, any>;
  error?: string;
  status?:
    | 'pending'
    | 'completed'
    | 'error'
    | 'awaiting_approval'
    | 'denied'
    | 'requires_client_execution';
  artifact_id?: string;
};
