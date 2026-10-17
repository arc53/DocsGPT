import { toolServiceOf, type ToolService } from '../connectors/toolService';
import type { Connection, ConnectorDefinition } from '../connectors/types';

type GroupableTool = {
  name: string;
  displayName?: string | null;
  customName?: string | null;
  connection_id?: string | null;
  config?: unknown;
};

export type ToolGroupKind = 'builtIn' | 'service' | 'custom';

export type ToolGroup<T> = {
  /** Stable React key: the kind, or the service's name. */
  key: string;
  kind: ToolGroupKind;
  /** The service a `service` group stands for (its name and icon). */
  service?: ToolService;
  tools: T[];
};

/**
 * A tool the user made from a template (an API tool, an MCP server with no
 * connection), as the composer and the agent builder group it.
 *
 * Args:
 *   tool: The tool.
 *
 * Returns:
 *   Whether it goes under Custom.
 */
export const isCustomTool = (tool: GroupableTool): boolean =>
  !tool.connection_id && (tool.name === 'api_tool' || tool.name === 'mcp_tool');

/**
 * The tools in the composer's groups: Built in, one per connected service
 * (in the order they first appear), then Custom. Empty groups are left out;
 * each group keeps the tools' order.
 *
 * Args:
 *   tools: The tools, as `/api/get_tools` returns them.
 *   connections: The caller's own connections.
 *   catalog: The connector catalog.
 *
 * Returns:
 *   The non-empty groups, in display order.
 */
export function groupTools<T extends GroupableTool>(
  tools: T[],
  connections: Connection[],
  catalog: ConnectorDefinition[],
): ToolGroup<T>[] {
  const builtIn: ToolGroup<T> = { key: 'builtIn', kind: 'builtIn', tools: [] };
  const custom: ToolGroup<T> = { key: 'custom', kind: 'custom', tools: [] };
  const services = new Map<string, ToolGroup<T>>();
  for (const tool of tools) {
    const service = toolServiceOf(tool, connections, catalog);
    if (service) {
      const key = `service:${service.name}`;
      const group = services.get(key) ?? {
        key,
        kind: 'service' as const,
        service,
        tools: [],
      };
      group.tools.push(tool);
      services.set(key, group);
    } else if (isCustomTool(tool)) {
      custom.tools.push(tool);
    } else {
      builtIn.tools.push(tool);
    }
  }
  return [builtIn, ...services.values(), custom].filter(
    (group) => group.tools.length > 0,
  );
}
