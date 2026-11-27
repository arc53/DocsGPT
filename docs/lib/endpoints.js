// Head metadata for the REST endpoint pages (app/API/endpoints/[...slug]),
// which have no frontmatter of their own.
import { lastUpdatedOf } from '../page-meta';
import { source } from './source';

const DESCRIPTION_LIMIT = 200;

/**
 * Markdown from the Swagger document as one line of plain text.
 *
 * @param {string} text Markdown: links, code spans, paragraphs.
 * @returns {string} The text without markup.
 */
function plainText(text) {
  return text
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Shortens a description to a search-result length, at a word boundary.
 *
 * @param {string} text Plain text.
 * @returns {string} At most DESCRIPTION_LIMIT characters.
 */
function clip(text) {
  if (text.length <= DESCRIPTION_LIMIT) return text;
  const cut = text.slice(0, DESCRIPTION_LIMIT - 1);
  return `${cut.slice(0, cut.lastIndexOf(' ')).replace(/[\s,;:.]+$/, '')}…`;
}

/**
 * An endpoint page's title, description and date, in the shape of a docs
 * page's frontmatter, for pageMetadata() and the JSON-LD.
 *
 * The description leads with the method and route; the date is the REST API
 * reference page's lastUpdated, which moves whenever the Swagger snapshot does.
 *
 * @param {import('fumadocs-core/source').Page} page An endpoint page from the loader.
 * @returns {{title: string, description: string, lastUpdated?: string}} The metadata.
 */
export function endpointMetadata(page) {
  const [operation] = page.data.getOpenAPIPageProps().operations ?? [];
  const route = operation ? `${operation.method.toUpperCase()} ${operation.path}` : '';
  const text = plainText(page.data.description ?? '');
  const description = clip([route && `${route} in the DocsGPT REST API.`, text].filter(Boolean).join(' '));
  return {
    title: page.data.title,
    description,
    lastUpdated: lastUpdatedOf(source.getPage(['API', 'reference'])?.data),
  };
}
