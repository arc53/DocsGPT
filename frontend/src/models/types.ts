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
}
