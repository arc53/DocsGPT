import { type AccessFields, can, isOwner } from './accessUtils';

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

/**
 * Whether a tool is on in the caller's own agentless chats (the "In my chats"
 * switch). The server sends `in_chat` for every row: the owner's `status`, or
 * a grantee's personal preference. Older payloads only carry `status`.
 */
export const toolInChat = (tool: {
  status?: boolean;
  in_chat?: boolean;
}): boolean => Boolean(tool.in_chat ?? tool.status);

/**
 * Whether the caller may add a tool to their own agents and chats: always
 * for their own tools, and for a shared one only with `use_in_own`.
 */
export const canAddToolToOwn = (tool: AccessFields): boolean =>
  isOwner(tool) || can(tool, 'use_in_own');

// Composer Tools picker: the chat-popup rule, minus shared tools the caller
// can't turn on for their own chats.
export const isChatPickerToolVisible = (
  tool: AccessFields & { default?: boolean; builtin?: boolean },
): boolean => isChatToolVisible(tool) && canAddToolToOwn(tool);

// Classic agent and workflow-node pickers: the classic rule, minus shared
// tools the caller can't add to their own agents (`use_in_own` off).
export const isAgentPickerToolVisible = (
  tool: AccessFields & { workflow_only?: boolean },
): boolean => isClassicAgentToolVisible(tool) && canAddToolToOwn(tool);
