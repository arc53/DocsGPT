import { searchPath } from 'fumadocs-core/breadcrumb';

import { source } from '../lib/source';
import { jsonLd, structuredData } from '../page-meta';

/**
 * The sidebar folders above a page that have a page of their own (their
 * index page, listed as the folder's first item), from the top level down.
 *
 * @param {string} route The page's route.
 * @returns {Array<{name: unknown, url: string}>} The folders, for the breadcrumb JSON-LD.
 */
function parentFolders(route) {
  const path = searchPath(source.getPageTree().children, route) ?? [];
  return path
    .filter((node) => node.type === 'folder')
    .map((folder) => {
      const index =
        folder.index ?? folder.children.find((child) => child.type === 'page' && route.startsWith(`${child.url}/`));
      return index ? { name: folder.name, url: index.url } : null;
    })
    .filter(Boolean);
}

/**
 * The page's JSON-LD scripts (see structuredData() in page-meta.js).
 *
 * @param {{route: string, metadata: Record<string, any>}} props The route and the page's title, description and
 *   lastUpdated.
 * @returns {import('react').JSX.Element[]} One script per JSON-LD object.
 */
export function PageJsonLd({ route, metadata }) {
  return structuredData({ route, metadata, parents: parentFolders(route) }).map((data) => (
    <script
      key={data['@type']}
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: jsonLd(data) }}
    />
  ));
}
