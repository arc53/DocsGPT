import type { TFunction } from 'i18next';

import { toolServiceOf, type ToolService } from '../connectors/toolService';
import type { Connection, ConnectorDefinition } from '../connectors/types';

type GroupableTool = {
  name: string;
  displayName?: string | null;
  customName?: string | null;
  connection_id?: string | null;
  config?: unknown;
  default?: boolean;
  builtin?: boolean;
};

/**
 * Where a tool comes from: `included` comes with DocsGPT (a default or
 * builtin tool), `added` was added and configured from the catalog,
 * `service` is from a connected service, `custom` is an API tool or MCP
 * server the user made.
 */
export type ToolGroupKind = 'included' | 'added' | 'service' | 'custom';

export type ToolGroup<T> = {
  /** Stable key: the kind, or `service:<name>`. */
  key: string;
  kind: ToolGroupKind;
  /** The service a `service` group stands for (its name and icon). */
  service?: ToolService;
  tools: T[];
};

/**
 * A tool the user made from a template (an API tool, an MCP server with no
 * connection).
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
 * A tool that comes with DocsGPT rather than one the user added: a default
 * chat tool, or a builtin the agent builder offers (Code Executor, Artifact).
 *
 * Args:
 *   tool: The tool.
 *
 * Returns:
 *   Whether it goes under Included.
 */
export const isIncludedTool = (tool: GroupableTool): boolean =>
  !tool.connection_id && Boolean(tool.default || tool.builtin);

/**
 * The tools in the groups every tool list shares (the chat picker, the agent
 * builder's picker and the Tools page): Included, Added, one per connected
 * service (in the order they first appear), then Custom. Empty groups are
 * left out; each group keeps the tools' order.
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
  const included: ToolGroup<T> = {
    key: 'included',
    kind: 'included',
    tools: [],
  };
  const added: ToolGroup<T> = { key: 'added', kind: 'added', tools: [] };
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
    } else if (isIncludedTool(tool)) {
      included.tools.push(tool);
    } else {
      added.tools.push(tool);
    }
  }
  return [included, added, ...services.values(), custom].filter(
    (group) => group.tools.length > 0,
  );
}

/**
 * A group's name as its heading says it; a service group is the service's
 * own name (its icon is drawn by `ToolGroupTitle`).
 *
 * Args:
 *   t: The translate function.
 *   group: The group.
 *
 * Returns:
 *   The group's name.
 */
export const toolGroupLabel = (
  t: TFunction,
  group: Pick<ToolGroup<unknown>, 'kind' | 'service'>,
): string =>
  group.kind === 'included'
    ? t('settings.tools.groupIncluded')
    : group.kind === 'added'
      ? t('settings.tools.groupAdded')
      : group.kind === 'custom'
        ? t('agents.form.toolsPopup.groupCustom')
        : (group.service?.name ?? '');
