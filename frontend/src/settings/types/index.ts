export type APIKeyData = {
  id: string;
  name: string;
  key: string;
  source: string;
  prompt_id: string;
  chunks: string;
};

export type LogData = {
  id: string;
  action: string;
  level: 'info' | 'error' | 'warning';
  user: string;
  question: string;
  response: string;
  sources: Record<string, any>[];
  retriever_params: Record<string, any>;
  timestamp: string;
};
