export type ModelSource = 'builtin' | 'user';

export interface AvailableModel {
  id: string;
  provider: string;
  display_name: string;
  description?: string;
  context_window: number;
  supported_attachment_types: string[];
  supports_tools: boolean;
  supports_structured_output: boolean;
  supports_streaming: boolean;
  enabled: boolean;
  source?: ModelSource;
}

export interface Model {
  id: string;
  value: string;
  provider: string;
  display_name: string;
  description?: string;
  context_window: number;
  supported_attachment_types: string[];
  supports_tools: boolean;
  supports_structured_output: boolean;
  supports_streaming: boolean;
  source?: ModelSource;
}

export interface CustomModelCapabilities {
  supports_tools: boolean;
  supports_structured_output: boolean;
  attachments: string[];
  context_window: number;
}

export interface CustomModel {
  id: string;
  upstream_model_id: string;
  display_name: string;
  description?: string;
  base_url: string;
  capabilities: CustomModelCapabilities;
  enabled: boolean;
  source: 'user';
}

export interface CreateCustomModelPayload {
  upstream_model_id: string;
  display_name: string;
  description?: string;
  base_url: string;
  api_key?: string;
  capabilities: CustomModelCapabilities;
  enabled: boolean;
}

export interface CustomModelTestResult {
  ok: boolean;
  error?: string;
}
