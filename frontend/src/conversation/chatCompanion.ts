import { createContext, useContext } from 'react';

/**
 * One retrieved source of an answer, as the backend labels a chunk.
 *
 * `text` is an excerpt: the live stream carries the first 100 characters, a
 * saved message up to 1,000. `source` is a file path for an uploaded source
 * or a URL for a crawled one. `source_id` and `chunk_key` find the full chunk
 * again (`/api/sources/<id>/chunk`); messages saved before retrieval carried
 * them have neither. `link` is the URL older web-search answers saved instead
 * of `source`.
 */
export type AnswerSource = {
  title: string;
  text: string;
  source?: string;
  link?: string;
  filename?: string;
  source_id?: string;
  chunk_key?: string;
  // A chunk synced from a connection names the service, never the account.
  connector_key?: string | null;
  connector_name?: string | null;
};

/**
 * The chat's one docked side panel slot (DESIGN.md "Side panels"): an answer
 * opens its sources there, beside the chat, replacing an open artifact.
 * `index` opens that source's reader instead of the list. Without a provider
 * (a shared chat, an agent preview) the answer opens its sources in a modal
 * SidePanel instead.
 */
export const ChatCompanionContext = createContext<{
  openSources: (sources: AnswerSource[], index?: number) => void;
} | null>(null);

export const useChatCompanion = () => useContext(ChatCompanionContext);

/** The source's web address, when it is one a browser can open. */
export function sourceHref(source: AnswerSource): string | null {
  const value = source.source ?? source.link ?? '';
  return /^https?:\/\//i.test(value) ? value : null;
}

/**
 * The excerpt the answer carried, without the ellipsis the stream appends.
 * It is a verbatim prefix of the chunk, so it can find a re-chunked one.
 */
export function sourceExcerpt(source: AnswerSource): string {
  return (source.text ?? '').replace(/\.\.\.$/, '').trim();
}
