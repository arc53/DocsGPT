import { createContext, useContext } from 'react';

import type { ArtifactCardItem } from './artifactCards';

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
  // A synced file's link in the service it came from (Google Drive...).
  url?: string;
  filename?: string;
  source_id?: string;
  chunk_key?: string;
  // A chunk synced from a connection names the service, never the account.
  connector_key?: string | null;
  connector_name?: string | null;
  // The decision model's p(relevant) against the searched query, when a
  // relevance stage ordered the answer's sources; absent otherwise.
  relevance?: number | null;
  // Left out of the answer by the agent's guardrails (a retrieval control
  // that blocks, such as the prompt-injection model): `text` is then a
  // placeholder, never the passage.
  withheld?: 'policy' | null;
};

/**
 * The chat's one docked side panel slot (DESIGN.md "Side panels"): an answer
 * opens its sources there, beside the chat, replacing an open artifact.
 * `index` opens that source's reader instead of the list. Without a provider
 * (a shared chat, an agent preview) the answer opens its sources in a modal
 * SidePanel instead.
 */
export const ChatCompanionContext = createContext<{
  /** Unset where sources keep their modal panel (the builder preview). */
  openSources?: (sources: AnswerSource[], index?: number) => void;
  /** The artifact (and version) the docked panel shows, so its card is marked open. */
  openArtifact?: { id: string; version?: number } | null;
  /**
   * Shows an answer's full artifact list (its “N more files” card). `key`
   * names the answer, so its card is marked open and its list kept current.
   */
  openArtifactList?: (items: ArtifactCardItem[], key: string) => void;
  /** The key of the answer whose list the panel shows. */
  openArtifactListKey?: string | null;
  /** An answer's current files; updates the panel's list when it is that answer's. */
  syncArtifactList?: (key: string, items: ArtifactCardItem[]) => void;
} | null>(null);

export const useChatCompanion = () => useContext(ChatCompanionContext);

/** The source's web address, when it is one a browser can open. */
export function sourceHref(source: AnswerSource): string | null {
  const isWeb = (value?: string) => !!value && /^https?:\/\//i.test(value);
  if (isWeb(source.url)) return source.url!;
  const value = source.source ?? source.link ?? '';
  return isWeb(value) ? value : null;
}

/**
 * The excerpt the answer carried, without the ellipsis the stream appends.
 * It is a verbatim prefix of the chunk, so it can find a re-chunked one.
 */
export function sourceExcerpt(source: AnswerSource): string {
  return (source.text ?? '').replace(/\.\.\.$/, '').trim();
}

export type RelevanceBand = 'strong' | 'possible' | 'weak';

/**
 * The coarse label a relevance score earns: strong from 0.7, possible from
 * 0.3, weak below. `null` for a source without a score, which shows no label.
 */
export function relevanceBand(relevance: unknown): RelevanceBand | null {
  if (typeof relevance !== 'number' || !Number.isFinite(relevance)) return null;
  if (relevance >= 0.7) return 'strong';
  if (relevance >= 0.3) return 'possible';
  return 'weak';
}
