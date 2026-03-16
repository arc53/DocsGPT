export type ToolSummary = {
  id: string;
  name: string;
  display_name: string;
};

export type Agent = {
  id?: string;
  name: string;
  description: string;
  image: string;
  source: string;
  sources?: string[];
  chunks: string;
  retriever: string;
  prompt_id: string;
  tools: string[];
  tool_details?: ToolSummary[];
  agent_type: string;
  status: string;
  key?: string;
  incoming_webhook_token?: string;
  pinned?: boolean;
  shared?: boolean;
  shared_token?: string;
  shared_metadata?: any;
  created_at?: string;
  updated_at?: string;
  last_used_at?: string;
  json_schema?: object;
  limited_token_mode?: boolean;
  token_limit?: number;
  limited_request_mode?: boolean;
  request_limit?: number;
  models?: string[];
  default_model_id?: string;
  folder_id?: string;
  workflow?: string;
};

export type AgentFolder = {
  id: string;
  name: string;
  parent_id?: string | null;
  created_at?: string;
  updated_at?: string;
};

export * from './workflow';
