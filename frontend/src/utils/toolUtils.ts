type ToolLabelSource = {
  customName?: string | null;
  displayName?: string | null;
  display_name?: string | null;
  name?: string | null;
};

const isNonEmptyString = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0;

export function getToolDisplayName(tool: ToolLabelSource): string {
  if (isNonEmptyString(tool.customName)) return tool.customName.trim();
  if (isNonEmptyString(tool.displayName)) return tool.displayName.trim();
  if (isNonEmptyString(tool.display_name)) return tool.display_name.trim();
  if (isNonEmptyString(tool.name)) return tool.name.trim();
  return '';
}

// Chat-popup visibility rule: show defaults (so users can toggle the
// agentless chat tools on/off) plus any non-builtin user_tools row. Hide
// pure builtins (agent-only). Dual-registered tools like ``scheduler``
// carry BOTH flags and stay visible via the ``default`` branch.
export const isChatToolVisible = (tool: {
  default?: boolean;
  builtin?: boolean;
}): boolean => Boolean(tool.default) || !tool.builtin;

// Classic agent picker visibility rule: hide ``workflow_only`` builtins
// (e.g. ``read_document``) so they surface only in the workflow-node picker.
// Everything else stays visible.
export const isClassicAgentToolVisible = (tool: {
  workflow_only?: boolean;
}): boolean => !tool.workflow_only;
