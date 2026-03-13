import { ConfigRequirements } from '../../modals/types';

export type ChunkType = {
  doc_id: string;
  text: string;
  metadata: { [key: string]: string };
};

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

export type ParameterGroupType = {
  type: 'object';
  properties: {
    [key: string]: {
      type: 'string' | 'integer';
      description: string;
      value: string | number;
      filled_by_llm: boolean;
      required?: boolean;
    };
  };
};

export type UserToolType = {
  id: string;
  name: string;
  displayName: string;
  customName?: string;
  description: string;
  status: boolean;
  config: {
    [key: string]: any;
  };
  configRequirements?: ConfigRequirements;
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
          required?: boolean;
        };
      };
      additionalProperties: boolean;
      required: string[];
      type: string;
    };
    active: boolean;
  }[];
};

export type APIActionType = {
  name: string;
  url: string;
  description: string;
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH' | 'HEAD' | 'OPTIONS';
  query_params: ParameterGroupType;
  headers: ParameterGroupType;
  body: ParameterGroupType;
  active: boolean;
  body_content_type?:
    | 'application/json'
    | 'application/x-www-form-urlencoded'
    | 'multipart/form-data'
    | 'text/plain'
    | 'application/xml'
    | 'application/octet-stream';
  body_encoding_rules?: {
    [key: string]: {
      style?: 'form' | 'spaceDelimited' | 'pipeDelimited' | 'deepObject';
      explode?: boolean;
    };
  };
};

export type APIToolType = {
  id: string;
  name: string;
  displayName: string;
  customName?: string;
  description: string;
  status: boolean;
  config: { actions: { [key: string]: APIActionType } };
  configRequirements?: ConfigRequirements;
};
