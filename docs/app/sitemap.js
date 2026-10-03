import { getPageMap } from 'nextra/page-map';

import { SITE_URL, flattenPages, lastUpdatedOf } from '../page-meta';

// Served at /sitemap.xml. One entry per page, in sidebar order; lastmod is the
// page's frontmatter lastUpdated, so it moves only when the content does.
export default async function sitemap() {
  const pages = flattenPages(await getPageMap());
  return pages.map(({ route, frontMatter }) => {
    const lastModified = lastUpdatedOf(frontMatter);
    return {
      url: route === '/' ? `${SITE_URL}/` : `${SITE_URL}${route}`,
      ...(lastModified ? { lastModified } : {}),
    };
  });
}
