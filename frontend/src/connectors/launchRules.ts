import type { ConnectorDefinition } from './types';

/** An MCP preset that signs in over OAuth: it goes through the wizard. */
export const isMcpPreset = (connector: ConnectorDefinition) =>
  connector.auth_kind === 'mcp_oauth' && !!connector.mcp_url;

/** Curated MCP servers that need no authentication. */
export const isMcpOpenPreset = (connector: ConnectorDefinition) =>
  connector.auth_kind === 'mcp' &&
  connector.publisher === 'preset' &&
  !!connector.mcp_url;

export const connectsInWizard = (connector: ConnectorDefinition) =>
  isMcpPreset(connector) || isMcpOpenPreset(connector);

/** Connectors whose sign-in the wizard redoes in place, with no form. */
export const reconnectsInPlace = (connector: ConnectorDefinition) =>
  connector.auth_kind === 'oauth' ||
  connector.auth_kind === 'api_key' ||
  isMcpPreset(connector);
