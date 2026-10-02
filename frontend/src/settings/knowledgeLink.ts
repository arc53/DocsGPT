import type { LinkedChunk } from '../components/chunkUtils';

/**
 * A place in Knowledge a citation opens: the source, and the chunk or wiki
 * page in it. `CitationReader` writes it into the URL and `Sources` reads it
 * back, opening the source's view there.
 */
export type KnowledgeLink = {
  sourceId: string;
  chunk?: LinkedChunk;
  wikiPage?: string;
};

/** The query keys a link uses; never `page`, which is the list's pagination. */
export const KNOWLEDGE_LINK_PARAMS = [
  'source',
  'chunk',
  'q',
  'path',
  'wikiPage',
] as const;

// The chunk browser's search is a substring match, and the excerpt's start
// is a verbatim prefix of the chunk, so this much finds it.
const SEARCH_LENGTH = 80;

/**
 * The Knowledge URL that opens `link`.
 *
 * @param link The source, and the chunk or wiki page in it.
 * @returns A path with its query string.
 */
export function knowledgeLink(link: KnowledgeLink): string {
  const params = new URLSearchParams({ source: link.sourceId });
  if (link.chunk?.id) params.set('chunk', link.chunk.id);
  const search = link.chunk?.search.slice(0, SEARCH_LENGTH).trim();
  if (search) params.set('q', search);
  if (link.chunk?.path) params.set('path', link.chunk.path);
  if (link.wikiPage) params.set('wikiPage', link.wikiPage);
  return `/settings/knowledge?${params.toString()}`;
}

/**
 * The link in a Knowledge URL's query, if it carries one.
 *
 * @param params The page's search params.
 * @returns The link, or null without a `source`.
 */
export function readKnowledgeLink(
  params: URLSearchParams,
): KnowledgeLink | null {
  const sourceId = params.get('source');
  if (!sourceId) return null;
  const link: KnowledgeLink = { sourceId };
  const id = params.get('chunk') ?? undefined;
  const search = params.get('q') ?? '';
  const path = params.get('path') ?? undefined;
  if (id || search || path) {
    link.chunk = { search, ...(id ? { id } : {}), ...(path ? { path } : {}) };
  }
  const wikiPage = params.get('wikiPage');
  if (wikiPage) link.wikiPage = wikiPage;
  return link;
}
