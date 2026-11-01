import apiClient from '../api/client';

/** Whether an agent has enough recent conversations for topic suggestions. */
export const TOPICS_STATUS_ENDPOINT = '/api/drafter/topics/status';

/** `GET /api/drafter/topics/status`. */
export type TopicsStatus = {
  available: boolean;
  /** Conversations in the window the suggestions read (the last 30 days). */
  conversations: number;
  /** How many it takes before suggestions are offered. */
  needed: number;
};

/** One suggested topic of a topics proposal. */
export type TopicSuggestion = {
  id: string;
  name: string;
  description: string;
  overlap: boolean;
  /** The fraction (0 to 1) of the sampled questions it would get; null when unknown. */
  share: number | null;
  /** `measured` by the decision model on real questions, or the drafting model's `estimate`. */
  share_kind: 'measured' | 'estimate';
  /** One of the agent's topics or folders it overlaps, by name. */
  similar_to: string | null;
  note: string | null;
};

/** The topics recipe's `proposal` payload. */
export type TopicsProposal = {
  message: string;
  sample: {
    questions: number;
    conversations: number;
    days: number;
    /** When shares were measured: the share of questions that fit no topic, before and after. */
    unmatched?: {
      before: number | null;
      after: number | null;
      questions: number;
    } | null;
  };
  topics: TopicSuggestion[];
  left_out: { name: string; reason: string }[];
  capacity: {
    one_per_question_free: number;
    overlapping_free: number;
    /** Folders the suggested one-per-question topics push out of the topic question. */
    pushes_out: string[];
  };
};

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const str = (value: unknown): string =>
  typeof value === 'string' ? value : '';

const num = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

/**
 * Read a `proposal` event's payload as a topics proposal, dropping anything
 * malformed; null when it isn't one.
 *
 * Args:
 *   raw: The event's `proposal`.
 *
 * Returns:
 *   The proposal, or null.
 */
export function parseTopicsProposal(raw: unknown): TopicsProposal | null {
  if (!isObject(raw) || !Array.isArray(raw.topics)) return null;
  const sample = isObject(raw.sample) ? raw.sample : {};
  const unmatched = isObject(sample.unmatched) ? sample.unmatched : null;
  const capacity = isObject(raw.capacity) ? raw.capacity : {};
  return {
    message: str(raw.message),
    sample: {
      questions: num(sample.questions) ?? 0,
      conversations: num(sample.conversations) ?? 0,
      days: num(sample.days) ?? 0,
      unmatched: unmatched
        ? {
            before: num(unmatched.before),
            after: num(unmatched.after),
            questions: num(unmatched.questions) ?? 0,
          }
        : null,
    },
    topics: raw.topics.filter(isObject).flatMap((topic) =>
      str(topic.id) && str(topic.name)
        ? [
            {
              id: str(topic.id),
              name: str(topic.name),
              description: str(topic.description),
              overlap: topic.overlap === true,
              share: num(topic.share),
              share_kind:
                topic.share_kind === 'measured' ? 'measured' : 'estimate',
              similar_to: str(topic.similar_to) || null,
              note: str(topic.note) || null,
            } satisfies TopicSuggestion,
          ]
        : [],
    ),
    left_out: (Array.isArray(raw.left_out) ? raw.left_out : [])
      .filter(isObject)
      .map((item) => ({ name: str(item.name), reason: str(item.reason) }))
      .filter((item) => item.name),
    capacity: {
      one_per_question_free: num(capacity.one_per_question_free) ?? 0,
      overlapping_free: num(capacity.overlapping_free) ?? 0,
      pushes_out: Array.isArray(capacity.pushes_out)
        ? capacity.pushes_out.filter(
            (name): name is string => typeof name === 'string',
          )
        : [],
    },
  };
}

/**
 * Read whether an agent has enough conversations for topic suggestions.
 *
 * Args:
 *   agentId: The agent.
 *   token: The session token.
 *   signal: Aborts the request.
 *
 * Returns:
 *   The status, or null when it can't be read (no edit access, an older
 *   server): suggestions then stay hidden.
 */
export async function getTopicsStatus(
  agentId: string,
  token: string | null,
  signal?: AbortSignal,
): Promise<TopicsStatus | null> {
  try {
    const response: Response = await apiClient.get(
      `${TOPICS_STATUS_ENDPOINT}?agent_id=${encodeURIComponent(agentId)}`,
      token,
      {},
      signal,
    );
    if (!response?.ok) return null;
    const data = (await response.json()) as Partial<TopicsStatus>;
    if (typeof data.available !== 'boolean') return null;
    return {
      available: data.available,
      conversations: num(data.conversations) ?? 0,
      needed: num(data.needed) ?? 0,
    };
  } catch {
    return null;
  }
}
