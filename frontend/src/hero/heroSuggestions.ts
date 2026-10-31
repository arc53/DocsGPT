import type {
  Connection,
  ConnectorCategory,
  ConnectorDefinition,
} from '../connectors/types';
import type { ConversationSummary } from '../preferences/types';
import { toolInChat } from '../utils/toolUtils';

/** A selected source the empty chat can suggest asking about. */
export type HeroSource = {
  id?: string;
  name: string;
  ingestStatus?: 'processing' | 'failed';
};

/** A connected service whose tool is on in the user's own chats. */
export type HeroService = {
  key: string;
  name: string;
  category: ConnectorCategory;
  icon: string;
};

/**
 * One row under the empty chat's model picker. The first four kinds are
 * content (a question to send, or a recent chat to open); the last three
 * are setup actions that open a page.
 */
export type HeroSuggestion =
  | { kind: 'summarize'; source: HeroSource }
  | { kind: 'compare'; first: HeroSource; second: HeroSource }
  | { kind: 'service'; service: HeroService }
  | { kind: 'continue'; chat: { id: string; name: string } }
  | { kind: 'addKnowledge' }
  | { kind: 'connect' }
  | { kind: 'createAgent' };

export type HeroSuggestionInput = {
  /** The sources picked in the composer's Knowledge. */
  selectedSources: HeroSource[];
  /** Whether the user has any source at all, picked or not. */
  hasSources: boolean;
  /** From `answerableServices`, most recently used first. */
  services: HeroService[];
  conversations: Pick<
    ConversationSummary,
    'id' | 'name' | 'agent_id' | 'date'
  >[];
  /** Whether the user has an agent of their own. */
  hasAgents: boolean;
  /** Nothing connected yet, and this install can connect something. */
  offerConnect: boolean;
  now: number;
};

const MAX_CONTENT_ROWS = 3;
const MAX_SERVICE_ROWS = 2;
const RECENT_MS = 7 * 24 * 60 * 60 * 1000;

/**
 * Whether a connector holds data a chat can ask about (files, docs, issues),
 * rather than being a web search or a bot that only sends messages.
 */
export const holdsData = (
  connector: Pick<ConnectorDefinition, 'category' | 'capabilities'>,
): boolean =>
  connector.category !== 'search' &&
  (connector.capabilities ?? []).some((c) => c === 'sync' || c === 'read');

/**
 * The connected services a question about would actually reach: the
 * connection is signed in, one of its tools is on in the user's own chats,
 * and the connector holds data. One per service, most recently used first.
 *
 * Args:
 *   catalog: The connector catalog.
 *   connections: The user's connections.
 *   tools: The user's tools (`connection_id` and the in-chat switch).
 *   nameOf: The service's display name, translated.
 *
 * Returns:
 *   The services, de-duplicated by connector.
 */
export function answerableServices({
  catalog,
  connections,
  tools,
  nameOf,
}: {
  catalog: ConnectorDefinition[];
  connections: Connection[];
  tools: {
    connection_id?: string | null;
    status?: boolean;
    in_chat?: boolean;
  }[];
  nameOf: (connector: ConnectorDefinition) => string;
}): HeroService[] {
  const inChat = new Set(
    tools
      .filter((tool) => tool.connection_id && toolInChat(tool))
      .map((tool) => tool.connection_id),
  );
  const lastUsed = (connection: Connection) =>
    connection.last_used_at ? Date.parse(connection.last_used_at) : 0;
  const seen = new Set<string>();
  const services: HeroService[] = [];
  [...connections]
    .filter((c) => c.status === 'connected' && inChat.has(c.id))
    .sort((a, b) => lastUsed(b) - lastUsed(a))
    .forEach((connection) => {
      const connector = catalog.find((d) => d.key === connection.connector_key);
      if (!connector || connector.publisher === 'custom') return;
      if (!holdsData(connector) || seen.has(connector.key)) return;
      seen.add(connector.key);
      services.push({
        key: connector.key,
        name: nameOf(connector),
        category: connector.category,
        icon: connector.icon,
      });
    });
  return services;
}

/** The latest named chat without an agent from the past week, if any. */
function recentChat(
  conversations: HeroSuggestionInput['conversations'],
  now: number,
): { id: string; name: string } | null {
  let latest: { id: string; name: string; at: number } | null = null;
  for (const chat of conversations) {
    if (chat.agent_id || !chat.date || !chat.name?.trim()) continue;
    const at = Date.parse(chat.date);
    if (Number.isNaN(at) || now - at > RECENT_MS) continue;
    if (!latest || at > latest.at)
      latest = { id: chat.id, name: chat.name, at };
  }
  return latest ? { id: latest.id, name: latest.name } : null;
}

/**
 * The empty chat's suggestion rows, built from what the user already has.
 *
 * Content comes first, at most three rows: the selected sources (summarize
 * the first, compare the first two), then connected services, then the
 * latest chat. One setup action follows (add knowledge, else connect). With
 * no content at all, every setup step not done yet shows instead.
 *
 * Args:
 *   input: What the user has; see `HeroSuggestionInput`.
 *
 * Returns:
 *   The rows in display order.
 */
export function buildHeroSuggestions(
  input: HeroSuggestionInput,
): HeroSuggestion[] {
  const content: HeroSuggestion[] = [];
  const sources = input.selectedSources.filter(
    (source) => source.id && !source.ingestStatus,
  );
  if (sources[0]) content.push({ kind: 'summarize', source: sources[0] });
  if (sources[1])
    content.push({ kind: 'compare', first: sources[0], second: sources[1] });
  input.services
    .slice(0, MAX_SERVICE_ROWS)
    .forEach((service) => content.push({ kind: 'service', service }));
  const chat = recentChat(input.conversations, input.now);
  if (chat) content.push({ kind: 'continue', chat });
  const rows = content.slice(0, MAX_CONTENT_ROWS);

  if (rows.length === 0) {
    if (!input.hasSources) rows.push({ kind: 'addKnowledge' });
    if (input.offerConnect) rows.push({ kind: 'connect' });
    if (!input.hasAgents) rows.push({ kind: 'createAgent' });
    return rows;
  }
  if (!input.hasSources) rows.push({ kind: 'addKnowledge' });
  else if (input.offerConnect) rows.push({ kind: 'connect' });
  return rows;
}
