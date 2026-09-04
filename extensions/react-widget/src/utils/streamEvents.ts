export interface StreamEvent {
  type?: string;
  [key: string]: unknown;
}

export interface ToolCallEvent {
  action_name?: string;
  tool_name?: string;
}

/** internal_search -> Internal Search */
export const prettifyName = (name: string): string =>
  name
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');

/**
 * Status-line text for a running workflow node, or null when the node is
 * scaffolding the user gains nothing from seeing. Keyed on node_type (a
 * closed enum) rather than node_title, which is free text like "agent node".
 */
export const workflowStepLabel = (event: StreamEvent): string | null => {
  if (event.status !== 'running') return null;
  switch (event.node_type) {
    case 'agent':
      return 'Thinking…';
    case 'code':
      return 'Running code…';
    case 'condition':
      return 'Deciding next step…';
    case 'start':
    case 'end':
    case 'state':
    case 'note':
      return null;
    default:
      return typeof event.node_title === 'string' && event.node_title
        ? `${prettifyName(event.node_title)}…`
        : null;
  }
};

export const toolNames = (calls: unknown): string[] => {
  if (!Array.isArray(calls)) return [];
  return calls
    .map((call: ToolCallEvent | null) => call?.action_name ?? call?.tool_name)
    .filter((name): name is string => Boolean(name));
};
