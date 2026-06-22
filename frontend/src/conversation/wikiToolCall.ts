import { ToolCallsType } from './types';

const WIKI_WRITE_ACTIONS = new Set([
  'wiki_create',
  'wiki_str_replace',
  'wiki_insert',
  'wiki_delete',
  'wiki_rename',
]);

export function isWikiWriteCall(toolCall: ToolCallsType): boolean {
  return (
    toolCall.tool_name === 'wiki' &&
    WIKI_WRITE_ACTIONS.has(toolCall.action_name)
  );
}

export function wikiWritePath(toolCall: ToolCallsType): string | null {
  const args = toolCall.arguments || {};
  const path = args.new_path ?? args.path;
  return typeof path === 'string' && path.length > 0 ? path : null;
}

export function wikiWriteActionKey(actionName: string): string {
  return actionName.replace(/^wiki_/, '');
}
