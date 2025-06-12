export type ToolCallsType = {
  tool_name: string;
  action_name: string;
  call_id: string;
  arguments: Record<string, any>;
  result?: Record<string, any>;
  status?: 'pending' | 'completed';
};
