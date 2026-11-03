import apiClient from '../client';

/**
 * MCP Apps: the view an MCP tool call renders in the chat
 * (`docsgpt/api/user/mcp_apps/routes.py`). The paths live here rather than
 * in `endpoints.ts`: they are one feature's.
 */
export const MCP_APPS_PATHS = {
  RESOURCE: '/api/mcp_apps/resource',
  CALL: '/api/mcp_apps/call',
} as const;

/** A tool's `CallToolResult`, as the view is handed it. */
export type McpCallToolResult = {
  content: Record<string, unknown>[];
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
};

/** The domains a view declares it reaches (`_meta.ui.csp`). */
export type McpAppCsp = {
  connectDomains?: string[];
  resourceDomains?: string[];
  frameDomains?: string[];
  baseUriDomains?: string[];
};

/** A view's HTML and what it declares, plus where the sandbox page is. */
export type McpAppResource = {
  html: string;
  csp?: McpAppCsp;
  permissions?: Record<string, Record<string, never>>;
  prefersBorder?: boolean;
  sandbox_url: string | null;
};

/** How a view's own tool call came back. */
export type McpAppCallOutcome =
  | { kind: 'result'; result: McpCallToolResult }
  | { kind: 'needs_approval' }
  | { kind: 'refused'; error: string };

/**
 * Read the view a tool call renders.
 *
 * @returns The view, or null when MCP Apps are off on this install (the chat
 *   then shows the ordinary tool step).
 * @throws When the view could not be loaded.
 */
export async function readMcpAppView(
  toolId: string,
  uri: string,
  token: string | null,
  signal?: AbortSignal,
): Promise<McpAppResource | null> {
  const response: Response = await apiClient.post(
    MCP_APPS_PATHS.RESOURCE,
    { tool_id: toolId, uri },
    token,
    {},
    signal,
  );
  if (response.status === 404) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body?.success)
    throw new Error(body?.error || `HTTP ${response.status}`);
  return body as McpAppResource;
}

/** Run a tool the view calls; `approved` once the user allowed a tool that needs approval. */
export async function callMcpAppTool(
  toolId: string,
  name: string,
  args: Record<string, unknown>,
  token: string | null,
  approved = false,
): Promise<McpAppCallOutcome> {
  const response: Response = await apiClient.post(
    MCP_APPS_PATHS.CALL,
    { tool_id: toolId, name, arguments: args, approved },
    token,
  );
  const body = await response.json().catch(() => ({}));
  if (response.status === 409 && body?.needs_approval)
    return { kind: 'needs_approval' };
  if (!response.ok || !body?.success)
    return {
      kind: 'refused',
      error: body?.error || `HTTP ${response.status}`,
    };
  return { kind: 'result', result: body.result as McpCallToolResult };
}
