/**
 * Which of an agent's tools a schedule must pre-approve.
 *
 * A scheduled run has nobody to approve a tool action, so the server refuses
 * every action that needs approval unless the schedule's `tool_allowlist`
 * holds that tool's id. Actions that never need approval run either way, so
 * the form lists only the tools with an action that needs approval, unticked
 * until the user ticks them.
 */

type ToolAction = {
  name?: string;
  active?: boolean;
  require_approval?: boolean;
};

/** The parts of a `/api/get_tools` row the approval check reads. */
export type ApprovalToolInfo = {
  id: string;
  name: string;
  displayName?: string;
  customName?: string;
  actions?: ToolAction[];
  config?: {
    require_approval?: boolean;
    actions?: Record<string, ToolAction>;
    [key: string]: unknown;
  };
};

/** One of the agent's tools as the agent read names it (`tool_details`). */
export type AgentToolSummary = {
  id: string;
  name: string;
  display_name?: string;
};

/** A tool the schedule form offers to pre-approve. */
export type ApprovalTool = { id: string; name: string };

/**
 * Whether any action of a tool asks for approval before it runs.
 *
 * Mirrors the server's gate: an API tool keeps its actions in its config, the
 * code executor's own `require_approval` setting wins over its action, and a
 * remote device decides per command from the device's live approval mode, so
 * it always counts as needing approval.
 */
export function toolNeedsApproval(tool: ApprovalToolInfo): boolean {
  if (tool.name === 'remote_device') return true;
  if (tool.name === 'code_executor' && tool.config?.require_approval) {
    return true;
  }
  const actions =
    tool.name === 'api_tool'
      ? Object.values(tool.config?.actions ?? {})
      : (tool.actions ?? []);
  return actions.some(
    (action) => action.active !== false && Boolean(action.require_approval),
  );
}

/**
 * The agent's tools a schedule has to pre-approve for them to act freely.
 *
 * A tool missing from the caller's tool list (one the owner didn't share
 * with them) can't be inspected, so it is listed too: better an extra
 * checkbox than an action approved without anyone choosing to.
 */
export function approvalGatedTools(
  agentTools: AgentToolSummary[],
  userTools: ApprovalToolInfo[],
): ApprovalTool[] {
  const byId = new Map(userTools.map((tool) => [String(tool.id), tool]));
  return agentTools.flatMap((tool) => {
    const info = byId.get(tool.id);
    if (info && !toolNeedsApproval(info)) return [];
    const name =
      info?.customName ||
      info?.displayName ||
      tool.display_name ||
      tool.name ||
      tool.id;
    return [{ id: tool.id, name }];
  });
}

/** The listed tools to show ticked: none for a new schedule, else the saved ones. */
export function initialApprovedIds(
  gatedIds: string[],
  saved: string[] | null | undefined,
): string[] {
  if (!saved) return [];
  const savedSet = new Set(saved);
  return gatedIds.filter((id) => savedSet.has(id));
}

/**
 * The `tool_allowlist` to send: the ticked tools, plus any saved entry the
 * form doesn't list (set through the API or the chat), which it leaves alone.
 */
export function buildToolAllowlist(
  gatedIds: string[],
  approvedIds: string[],
  saved: string[] | null | undefined,
): string[] {
  const gated = new Set(gatedIds);
  const kept = (saved ?? []).filter((id) => !gated.has(id));
  return [...kept, ...approvedIds.filter((id) => gated.has(id))];
}
