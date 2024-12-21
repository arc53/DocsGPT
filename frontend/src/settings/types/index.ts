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

export type UserTool = {
  id: string;
  name: string;
  displayName: string;
  description: string;
  status: boolean;
  config: {
    [key: string]: string;
  };
  actions: {
    name: string;
    description: string;
    parameters: {
      properties: {
        [key: string]: {
          type: string;
          description: string;
          filled_by_llm: boolean;
          value: string;
        };
      };
      additionalProperties: boolean;
      required: string[];
      type: string;
    };
    active: boolean;
  }[];
};
