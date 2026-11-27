export type ConfigFieldSpec = {
  type: 'string' | 'number' | 'boolean';
  label: string;
  description: string;
  required?: boolean;
  secret?: boolean;
  order?: number;
  enum?: string[];
  default?: string | number | boolean;
  depends_on?: { [key: string]: string };
};

export type ConfigRequirements = {
  [key: string]: ConfigFieldSpec;
};

export type AvailableToolType = {
  name: string;
  displayName: string;
  description: string;
  configRequirements: ConfigRequirements;
  actions: {
    name: string;
    description: string;
    parameters: object;
  }[];
  /** `built_in`, `service` (a connector's tool) or `custom` (MCP / OpenAPI). */
  group?: 'built_in' | 'service' | 'custom';
  connector_key?: string | null;
  /**
   * In a team, on a service tool: the team has no account for it, so only
   * "each person signs in with their own account" is on offer.
   */
  member_only?: boolean;
};
