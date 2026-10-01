import type { TFunction } from 'i18next';

import type { ToolCallsType } from '../conversation/types';

const WEB_SEARCH_ACTIONS = new Set([
  'brave_web_search',
  'ddg_web_search',
  'ddg_news_search',
]);
const IMAGE_SEARCH_ACTIONS = new Set([
  'brave_image_search',
  'ddg_image_search',
]);
const ARTIFACT_ACTIONS = new Set([
  'create_artifact',
  'edit_artifact',
  'rewrite_artifact',
]);

// Display-name overrides for tools whose label differs from the formatted key.
const TOOL_LABEL_OVERRIDES: Record<string, string> = {
  artifact_generator: 'Artifact',
};

function formatToolLabel(toolName: string | undefined): string {
  if (!toolName) return '';
  if (TOOL_LABEL_OVERRIDES[toolName]) return TOOL_LABEL_OVERRIDES[toolName];
  return toolName
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}

// i18n.ts leaves escapeValue at its default (true); React escapes on render,
// so disable it here to keep user queries like O'Brien readable.
const NO_ESCAPE = { interpolation: { escapeValue: false } } as const;

/**
 * An activity as an i18n key suffix plus values, so the present- and past-tense
 * phrasings stay two lookups of one mapping instead of two mappings.
 */
export type ToolActivity = { key: string; values?: Record<string, string> };

const CONNECTOR_SEARCH_WORDS = /search|query|find|list/i;

/**
 * An action's name in words, without the service prefix it repeats:
 * "linear_create_issue" and "notion-create-pages" drop "linear" / "notion";
 * a bare verb ("search") keeps its whole name. Lower case.
 *
 * @param action - The action's name as the model called it.
 * @param service - The service's name, whose prefix is dropped.
 */
export function readableAction(action: string, service?: string | null) {
  return action
    .replace(/^[a-z0-9]+[_-](?=[a-z])/i, (prefix) =>
      service &&
      service.toLowerCase().startsWith(prefix.slice(0, -1).toLowerCase())
        ? ''
        : prefix,
    )
    .replace(/[_-]+/g, ' ')
    .trim()
    .toLowerCase();
}

/**
 * A call's card title: "GitHub · Create issue", or the tool's name when no
 * connection backs it ("Remote Device · Run command").
 */
export function toolCallTitle(toolCall: ToolCallsType, t: TFunction): string {
  const name = toolCall.connector_name || formatToolLabel(toolCall.tool_name);
  const words = readableAction(
    toolCall.action_name ?? '',
    toolCall.connector_name,
  );
  const action = words.charAt(0).toUpperCase() + words.slice(1);
  if (!name) return action;
  if (!action) return name;
  return t('conversation.toolApproval.title', { name, action, ...NO_ESCAPE });
}

/**
 * A call to a connection-backed tool, named after its service: "Searched
 * Notion", "Read from Google Drive", "Used Linear: create issue". Reads that
 * look up something search; other reads read; writes name their action.
 */
function describeConnectorCall(toolCall: ToolCallsType): ToolActivity | null {
  const name = toolCall.connector_name;
  if (!name) return null;
  const action = toolCall.action_name ?? '';
  if (toolCall.access === 'write') {
    return {
      key: 'connectorWrite',
      values: { name, action: readableAction(action, name) },
    };
  }
  if (CONNECTOR_SEARCH_WORDS.test(action))
    return { key: 'connectorSearch', values: { name } };
  return { key: 'connectorRead', values: { name } };
}

// Connector activities read differently while running and once done.
const CONNECTOR_KEYS: Record<
  'streamingStatus' | 'toolChip',
  Record<string, string>
> = {
  streamingStatus: {
    connectorSearch: 'searchingConnector',
    connectorRead: 'usingConnector',
    connectorWrite: 'usingConnector',
  },
  toolChip: {
    connectorSearch: 'searchedConnector',
    connectorRead: 'readConnector',
    connectorWrite: 'usedConnector',
  },
};

export function describeToolCall(toolCall: ToolCallsType): ToolActivity {
  const { tool_name, action_name, arguments: args } = toolCall;
  const query = typeof args?.query === 'string' ? args.query : undefined;

  if (WEB_SEARCH_ACTIONS.has(action_name))
    return query ? { key: 'searchingWeb', values: { query } } : { key: 'web' };
  if (IMAGE_SEARCH_ACTIONS.has(action_name))
    return query
      ? { key: 'searchingImages', values: { query } }
      : { key: 'web' };
  if (action_name === 'read_webpage') {
    const url = typeof args?.url === 'string' ? args.url : undefined;
    if (url) {
      let target = url;
      try {
        target = new URL(url).hostname;
      } catch {
        // not a parseable url; show it as given
      }
      return { key: 'readingPage', values: { target } };
    }
  }
  const connector = describeConnectorCall(toolCall);
  if (connector) return connector;
  if (action_name === 'run_code') return { key: 'runningCode' };
  if (ARTIFACT_ACTIONS.has(action_name)) return { key: 'creatingArtifact' };
  if (tool_name === 'internal_search') return { key: 'searchingKnowledge' };
  if (tool_name === 'memory' || tool_name === 'notes')
    return { key: 'accessingMemory' };

  return { key: 'usingTool', values: { tool: formatToolLabel(tool_name) } };
}

// The generic-search fallback key differs between the two namespaces.
const GENERIC_SEARCH_KEY: Record<string, string> = {
  streamingStatus: 'searchingWebGeneric',
  toolChip: 'searchedWebGeneric',
};

function activityLabel(
  activity: ToolActivity,
  namespace: 'streamingStatus' | 'toolChip',
  t: TFunction,
): string {
  const key =
    activity.key === 'web'
      ? GENERIC_SEARCH_KEY[namespace]
      : (CONNECTOR_KEYS[namespace][activity.key] ?? activity.key);
  return t(
    `conversation.${namespace}.${key}`,
    activity.values ? { ...activity.values, ...NO_ESCAPE } : undefined,
  );
}

/**
 * Whether the call has been handed off and not come back yet. A call the client
 * still has to execute counts: it has no result either.
 */
export function isToolCallRunning(toolCall: {
  status?: ToolCallsType['status'];
}): boolean {
  return (
    toolCall.status === 'pending' ||
    toolCall.status === 'requires_client_execution'
  );
}

export function getToolChipLabel(
  toolCall: ToolCallsType,
  t: TFunction,
): string {
  const activity = describeToolCall(toolCall);
  const namespace = isToolCallRunning(toolCall)
    ? 'streamingStatus'
    : 'toolChip';
  return activityLabel(activity, namespace, t);
}
