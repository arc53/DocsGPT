import { endpointMetadata } from '../lib/endpoints';
import { source } from '../lib/source';
import { SITE_URL, lastUpdatedOf } from '../page-meta';

// Served at /sitemap.xml. One entry per page, the REST endpoint pages included;
// lastmod is the page's frontmatter lastUpdated (for an endpoint page, the REST
// API reference's), so it moves only when the content does.
export default function sitemap() {
  return source.getPages().map((page) => {
    const lastModified = lastUpdatedOf(page.type === 'openapi' ? endpointMetadata(page) : page.data);
    return {
      url: page.url === '/' ? `${SITE_URL}/` : `${SITE_URL}${page.url}`,
      ...(lastModified ? { lastModified } : {}),
    };
  });
}
