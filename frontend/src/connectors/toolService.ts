import type { Connection, ConnectorDefinition } from './types';

/** The service a connected tool comes from, as the pickers group it. */
export type ToolService = {
  name: string;
  /** A `ConnectorIcon` name; null draws the tool's own icon. */
  icon: string | null;
  /** Set only when the connection is the caller's own. */
  connection?: Connection;
  connector?: ConnectorDefinition;
};

type ToolLike = {
  name: string;
  displayName?: string | null;
  customName?: string | null;
  connection_id?: string | null;
  config?: unknown;
};

// Templates any server can use (an MCP server, an OpenAPI spec): a tool
// made from one belongs to its connection, not to a connector. Mirrors
// `_GENERIC_TOOL_TEMPLATES` in `docsgpt/connectors/catalog.py`.
const GENERIC_TEMPLATES = new Set(['mcp_tool', 'api_tool']);

// `scheme://host`, the part of an MCP URL a connection is keyed on.
const baseUrl = (url: unknown): string => {
  if (typeof url !== 'string' || !url) return '';
  try {
    const parsed = new URL(url);
    return `${parsed.protocol}//${parsed.host}`;
  } catch {
    return '';
  }
};

// The catalog connector a tool was made from, found from the tool alone: a
// built-in service by its tool template, an MCP preset by its server.
const connectorForTool = (
  tool: ToolLike,
  catalog: ConnectorDefinition[],
): ConnectorDefinition | undefined => {
  if (!GENERIC_TEMPLATES.has(tool.name)) {
    return catalog.find(
      (c) =>
        c.publisher === 'built_in' && c.tool_templates?.includes(tool.name),
    );
  }
  if (tool.name !== 'mcp_tool') return undefined;
  const server = baseUrl(
    (tool.config as { server_url?: unknown } | undefined)?.server_url,
  );
  if (!server) return undefined;
  return catalog.find(
    (c) =>
      c.publisher !== 'custom' && !!c.mcp_url && baseUrl(c.mcp_url) === server,
  );
};

/**
 * The service a tool with a connection belongs to, for grouping it in the
 * tool pickers. The caller's own connection names it; a teammate's
 * connection is never in the caller's list, so a shared tool is named from
 * the catalog, or failing that from its own name without the " · account"
 * the server adds. Undefined for a tool with no connection.
 *
 * Args:
 *   tool: The tool, as `/api/get_tools` returns it.
 *   connections: The caller's own connections.
 *   catalog: The connector catalog.
 *
 * Returns:
 *   The group name and icon, or undefined.
 */
export function toolServiceOf(
  tool: ToolLike,
  connections: Connection[],
  catalog: ConnectorDefinition[],
): ToolService | undefined {
  if (!tool.connection_id) return undefined;
  const connection = connections.find((c) => c.id === tool.connection_id);
  if (connection) {
    const connector = catalog.find((c) => c.key === connection.connector_key);
    return {
      name: connection.name,
      icon: connection.icon,
      connection,
      ...(connector && { connector }),
    };
  }
  const connector = connectorForTool(tool, catalog);
  if (connector) {
    return { name: connector.name, icon: connector.icon, connector };
  }
  const own = (tool.displayName || tool.customName || tool.name).split(
    ' · ',
  )[0];
  return { name: own, icon: null };
}
