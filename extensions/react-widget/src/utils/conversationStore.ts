import type { FEEDBACK, Query } from '../types/index';

/**
 * The visitor's conversations, kept in `localStorage` so a reload continues
 * where they left off. Every storage access is guarded: private mode, a full
 * quota or blocked storage fall back to memory without an error.
 */

export const STORE_VERSION = 1;
/** Conversations kept per agent; the oldest go first. */
export const MAX_CONVERSATIONS = 30;
/** About 1 MB of JSON; localStorage quotas are counted in UTF-16 units. */
export const MAX_STORE_CHARS = 1_000_000;
const TITLE_MAX_CHARS = 80;

type Source = NonNullable<Query['sources']>[number];

/** A turn as stored: only what renders it again, never file contents. */
export interface StoredTurn {
  prompt: string;
  response?: string;
  sources?: Source[];
  toolCalls?: string[];
  feedback?: FEEDBACK;
  error?: string;
  errorKey?: Query['errorKey'];
  /** Server ids, kept so Retry can resend the files. */
  attachments?: { id: string; name: string }[];
}

export interface StoredConversation {
  /** Local id; the server's is `conversationId`. */
  id: string;
  conversationId: string | null;
  /** The first question, shortened. */
  title: string;
  createdAt: number;
  updatedAt: number;
  turns: StoredTurn[];
}

export interface StoredState {
  version: typeof STORE_VERSION;
  activeId: string | null;
  conversations: StoredConversation[];
}

export const emptyState = (): StoredState => ({
  version: STORE_VERSION,
  activeId: null,
  conversations: [],
});

/** 32-bit FNV-1a as hex: short, stable, and not the raw key. */
export const fnv1a = (input: string): string => {
  let hash = 0x811c9dc5;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
};

/**
 * The storage key for one agent, so two agents on a site don't mix. `name`
 * suffixes it for other per-agent values, e.g. a panel width.
 */
export const storageKey = (apiHost: string, apiKey: string, name?: string) =>
  `docsgpt-widget:v1:${fnv1a(`${apiHost.replace(/\/+$/, '')}\n${apiKey}`)}${
    name ? `:${name}` : ''
  }`;

const localStorageOrNull = (): Storage | null => {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    // Reading the property itself throws where storage is blocked.
    return null;
  }
};

/** The stored string, or null when unset or unreadable. */
export const readStorage = (key: string): string | null => {
  try {
    return localStorageOrNull()?.getItem(key) ?? null;
  } catch {
    return null;
  }
};

/** True once written; false when storage is blocked or full. */
export const writeStorage = (key: string, value: string): boolean => {
  try {
    const storage = localStorageOrNull();
    if (!storage) return false;
    storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
};

export const removeStorage = (key: string) => {
  try {
    localStorageOrNull()?.removeItem(key);
  } catch {
    // Nothing stored that could be read either.
  }
};

/** A local id; crypto.randomUUID needs a secure origin. */
export const newConversationId = () =>
  `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;

/** The first question on one line, cut to about 80 characters. */
export const conversationTitle = (prompt: string) => {
  const line = prompt.replace(/\s+/g, ' ').trim();
  return line.length > TITLE_MAX_CHARS
    ? `${line.slice(0, TITLE_MAX_CHARS - 1).trimEnd()}…`
    : line;
};

/** A turn still streaming keeps only its question, so a reload shows it interrupted. */
export const toStoredTurn = (query: Query, streaming = false): StoredTurn => {
  const turn: StoredTurn = { prompt: query.prompt };
  if (!streaming) {
    if (query.response) turn.response = query.response;
    if (query.sources?.length)
      turn.sources = query.sources.map(({ title, text, source }) => ({
        title,
        text,
        source,
      }));
    if (query.toolCalls?.length) turn.toolCalls = [...query.toolCalls];
    if (query.feedback) turn.feedback = query.feedback;
    if (query.error) {
      turn.error = query.error;
      if (query.errorKey) turn.errorKey = query.errorKey;
    }
  }
  if (query.attachments?.length)
    turn.attachments = query.attachments.map(({ id, fileName }) => ({
      id,
      name: fileName,
    }));
  return turn;
};

/**
 * A stored turn as the chat renders it. One with neither an answer nor an
 * error was cut off mid-stream, and comes back as a failure to retry.
 */
export const fromStoredTurn = (
  turn: StoredTurn,
  interruptedText: string,
): Query => {
  const query: Query = { prompt: turn.prompt };
  if (turn.response) query.response = turn.response;
  if (turn.sources?.length) query.sources = turn.sources;
  if (turn.toolCalls?.length) query.toolCalls = turn.toolCalls;
  if (turn.feedback) query.feedback = turn.feedback;
  if (turn.error) {
    query.error = turn.error;
    if (turn.errorKey) query.errorKey = turn.errorKey;
  }
  if (turn.attachments?.length)
    query.attachments = turn.attachments.map(({ id, name }) => ({
      id,
      fileName: name,
    }));
  if (!query.response && !query.error) {
    query.error = interruptedText;
    query.errorKey = 'interrupted';
  }
  return query;
};

const isString = (value: unknown): value is string => typeof value === 'string';

const parseTurn = (value: unknown): StoredTurn | null => {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  if (!isString(raw.prompt)) return null;
  const turn: StoredTurn = { prompt: raw.prompt };
  if (isString(raw.response)) turn.response = raw.response;
  if (Array.isArray(raw.sources))
    turn.sources = raw.sources
      .filter((source) => source && typeof source === 'object')
      .map((source: Record<string, unknown>) => ({
        title: isString(source.title) ? source.title : '',
        text: isString(source.text) ? source.text : '',
        source: isString(source.source) ? source.source : '',
      }));
  if (Array.isArray(raw.toolCalls))
    turn.toolCalls = raw.toolCalls.filter(isString);
  if (raw.feedback === 'LIKE' || raw.feedback === 'DISLIKE')
    turn.feedback = raw.feedback;
  if (isString(raw.error)) {
    turn.error = raw.error;
    if (raw.errorKey === 'connectionError' || raw.errorKey === 'interrupted')
      turn.errorKey = raw.errorKey;
  }
  if (Array.isArray(raw.attachments))
    turn.attachments = raw.attachments
      .filter((item) => item && isString(item.id) && isString(item.name))
      .map(({ id, name }: { id: string; name: string }) => ({ id, name }));
  return turn;
};

const parseConversation = (value: unknown): StoredConversation | null => {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  if (!isString(raw.id) || !Array.isArray(raw.turns)) return null;
  const turns = raw.turns
    .map(parseTurn)
    .filter((turn): turn is StoredTurn => turn !== null);
  if (turns.length === 0) return null;
  const updatedAt = Number(raw.updatedAt) || 0;
  return {
    id: raw.id,
    conversationId: isString(raw.conversationId) ? raw.conversationId : null,
    title: isString(raw.title) ? raw.title : conversationTitle(turns[0].prompt),
    createdAt: Number(raw.createdAt) || updatedAt,
    updatedAt,
    turns,
  };
};

/** Stored JSON as state; anything unreadable or from another version is empty. */
export const parseState = (raw: string | null): StoredState => {
  if (!raw) return emptyState();
  try {
    const data = JSON.parse(raw) as Record<string, unknown>;
    if (!data || data.version !== STORE_VERSION) return emptyState();
    const conversations = Array.isArray(data.conversations)
      ? data.conversations
          .map(parseConversation)
          .filter((item): item is StoredConversation => item !== null)
      : [];
    const activeId =
      isString(data.activeId) &&
      conversations.some((item) => item.id === data.activeId)
        ? data.activeId
        : null;
    return { version: STORE_VERSION, activeId, conversations };
  } catch {
    return emptyState();
  }
};

const byNewest = (a: StoredConversation, b: StoredConversation) =>
  b.updatedAt - a.updatedAt;

/**
 * Drops the oldest conversations until at most `maxConversations` remain and
 * the JSON fits `maxChars`. The active one goes last: first its oldest turns,
 * keeping the latest.
 */
export const fitState = (
  state: StoredState,
  maxConversations = MAX_CONVERSATIONS,
  maxChars = MAX_STORE_CHARS,
): StoredState => {
  let conversations = [...state.conversations].sort(byNewest);
  const dropOldest = () => {
    for (let index = conversations.length - 1; index >= 0; index -= 1) {
      if (conversations[index].id !== state.activeId) {
        conversations = conversations.filter((_, i) => i !== index);
        return true;
      }
    }
    return false;
  };
  while (conversations.length > maxConversations && dropOldest());
  const size = () => JSON.stringify({ ...state, conversations }).length;
  while (size() > maxChars && dropOldest());
  while (size() > maxChars) {
    const active = conversations.find((item) => item.id === state.activeId);
    if (!active || active.turns.length <= 1) break;
    conversations = conversations.map((item) =>
      item === active ? { ...item, turns: item.turns.slice(1) } : item,
    );
  }
  return { ...state, conversations };
};

/** Saves `conversation` (new or changed) and makes it the active one. */
export const upsertConversation = (
  state: StoredState,
  conversation: Omit<StoredConversation, 'createdAt'> & { createdAt?: number },
): StoredState => {
  const existing = state.conversations.find(
    (item) => item.id === conversation.id,
  );
  const saved: StoredConversation = {
    ...conversation,
    createdAt:
      existing?.createdAt ?? conversation.createdAt ?? conversation.updatedAt,
  };
  return {
    ...state,
    activeId: conversation.id,
    conversations: [
      saved,
      ...state.conversations.filter((item) => item.id !== conversation.id),
    ],
  };
};

export const removeConversation = (
  state: StoredState,
  id: string,
): StoredState => ({
  ...state,
  activeId: state.activeId === id ? null : state.activeId,
  conversations: state.conversations.filter((item) => item.id !== id),
});

export interface ConversationStore {
  key: string;
  read: () => StoredState;
  /** Applies `change` to the latest stored state (another tab may have written), then saves. */
  update: (change: (state: StoredState) => StoredState) => StoredState;
  /** Removes everything stored under the key. */
  clear: () => void;
}

/**
 * One agent's conversations. Writes go to storage when it works; the last
 * state is also kept in memory, which serves reads while storage fails.
 */
export const createConversationStore = (key: string): ConversationStore => {
  let memory = emptyState();
  let usingMemory = false;

  const read = () => {
    if (usingMemory) return memory;
    if (!localStorageOrNull()) {
      usingMemory = true;
      return memory;
    }
    return parseState(readStorage(key));
  };

  const write = (state: StoredState) => {
    memory = state;
    let fitted = state;
    // A quota below our own cap: shed the oldest until the write lands.
    for (;;) {
      if (writeStorage(key, JSON.stringify(fitted))) {
        usingMemory = false;
        return;
      }
      const smaller = fitState(fitted, fitted.conversations.length - 1);
      if (smaller.conversations.length === fitted.conversations.length) break;
      fitted = smaller;
    }
    usingMemory = true;
  };

  return {
    key,
    read,
    update: (change) => {
      const next = fitState(change(read()));
      write(next);
      return next;
    },
    clear: () => {
      memory = emptyState();
      usingMemory = false;
      removeStorage(key);
    },
  };
};

export type HistoryGroup = 'today' | 'yesterday' | 'previous7Days' | 'older';

const DAY_MS = 24 * 60 * 60 * 1000;

const startOfDay = (time: number, daysBack = 0) => {
  const date = new Date(time);
  date.setHours(0, 0, 0, 0);
  // setDate, not milliseconds, so a DST change doesn't shift the boundary.
  date.setDate(date.getDate() - daysBack);
  return date.getTime();
};

/** The history group a timestamp falls in, by the visitor's calendar days. */
export const historyGroup = (time: number, now: number): HistoryGroup => {
  if (time >= startOfDay(now)) return 'today';
  if (time >= startOfDay(now, 1)) return 'yesterday';
  if (time >= startOfDay(now, 7)) return 'previous7Days';
  return 'older';
};

const GROUP_ORDER: HistoryGroup[] = [
  'today',
  'yesterday',
  'previous7Days',
  'older',
];

/** Non-empty groups in display order, newest first within each. */
export const groupConversations = (
  conversations: StoredConversation[],
  now: number,
) => {
  const sorted = [...conversations].sort(byNewest);
  return GROUP_ORDER.map((group) => ({
    group,
    items: sorted.filter((item) => historyGroup(item.updatedAt, now) === group),
  })).filter((entry) => entry.items.length > 0);
};

/**
 * "5 minutes ago", "yesterday", "3 days ago" in `locale`, then a date once
 * past a week.
 */
export const relativeDate = (time: number, now: number, locale: string) => {
  const elapsed = Math.max(0, now - time);
  try {
    const relative = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
    if (time >= startOfDay(now)) {
      if (elapsed < 60 * 1000) return relative.format(0, 'second');
      if (elapsed < 60 * 60 * 1000)
        return relative.format(-Math.floor(elapsed / 60000), 'minute');
      return relative.format(-Math.floor(elapsed / 3600000), 'hour');
    }
    const days = Math.round((startOfDay(now) - startOfDay(time)) / DAY_MS);
    if (days < 7) return relative.format(-days, 'day');
  } catch {
    // An engine without RelativeTimeFormat; the date below still reads.
  }
  const sameYear = new Date(time).getFullYear() === new Date(now).getFullYear();
  try {
    return new Intl.DateTimeFormat(locale, {
      month: 'short',
      day: 'numeric',
      year: sameYear ? undefined : 'numeric',
    }).format(time);
  } catch {
    return new Date(time).toLocaleDateString();
  }
};
