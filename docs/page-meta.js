// A docs page's head metadata: the canonical URL, the share card, the
// last-updated date and the JSON-LD.
// app/[[...mdxPath]]/page.jsx and app/sitemap.js both build on these helpers,
// so the date a reader sees, the sitemap's lastmod and the structured data's
// dateModified always agree.

export const SITE_URL = 'https://docs.docsgpt.cloud';
export const SITE_NAME = 'DocsGPT Docs';
export const HOME_TITLE = 'DocsGPT Documentation';

const OG_IMAGE = {
  url: '/og/default.png',
  width: 1200,
  height: 630,
  alt: 'DocsGPT documentation: quickstart, sources, agents, deploying and the API.',
};

// The same organization www.docsgpt.cloud describes in its JSON-LD.
const PUBLISHER = {
  '@type': 'Organization',
  '@id': 'https://www.docsgpt.cloud/#organization',
  name: 'Arc53',
  url: 'https://www.arc53.com/',
  logo: 'https://www.docsgpt.cloud/web-app-manifest-512x512.png',
};

const WEBSITE_ID = `${SITE_URL}/#website`;

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * The route a page is served at.
 *
 * @param {string[] | undefined} mdxPath The catch-all segments.
 * @returns {string} The route, "/" for the home page.
 */
export function routeOf(mdxPath) {
  return mdxPath?.length ? `/${mdxPath.join('/')}` : '/';
}

/**
 * A page's frontmatter `lastUpdated` date.
 *
 * @param {Record<string, unknown> | undefined} frontMatter The page's frontmatter.
 * @returns {string | undefined} The date as YYYY-MM-DD, or undefined when absent or malformed.
 */
export function lastUpdatedOf(frontMatter) {
  const value = frontMatter?.lastUpdated;
  return typeof value === 'string' && DATE_RE.test(value) ? value : undefined;
}

/**
 * The timestamp the theme's "Last updated on" line shows for a date.
 *
 * Noon UTC, so the calendar day reads the same in every timezone from UTC-11 to UTC+11.
 *
 * @param {string | undefined} date YYYY-MM-DD.
 * @returns {number | undefined} Milliseconds since the epoch.
 */
export function timestampOf(date) {
  return date ? Date.parse(`${date}T12:00:00Z`) : undefined;
}

/**
 * Every page in Nextra's page map, in sidebar order.
 *
 * @param {Array<Record<string, any>>} pageMap The result of getPageMap().
 * @returns {Array<{route: string, frontMatter: Record<string, unknown>}>} One entry per page.
 */
export function flattenPages(pageMap) {
  const pages = [];
  for (const item of pageMap) {
    if (Array.isArray(item.children)) pages.push(...flattenPages(item.children));
    else if (item.route && item.frontMatter) pages.push({ route: item.route, frontMatter: item.frontMatter });
  }
  return pages;
}

/**
 * The Next.js metadata for a page: title, description, canonical URL and share card.
 *
 * @param {string} route The page's route.
 * @param {Record<string, any>} metadata The page metadata from Nextra's importPage().
 * @returns {import('next').Metadata} The page's metadata.
 */
export function pageMetadata(route, metadata) {
  const isHome = route === '/';
  const title = isHome ? HOME_TITLE : metadata.title;
  const { description } = metadata;
  const modified = lastUpdatedOf(metadata);
  return {
    title: isHome ? { absolute: HOME_TITLE } : title,
    description,
    alternates: { canonical: route },
    openGraph: {
      type: isHome ? 'website' : 'article',
      siteName: SITE_NAME,
      locale: 'en_US',
      url: route,
      title,
      description,
      images: [OG_IMAGE],
      ...(modified && !isHome ? { modifiedTime: modified } : {}),
    },
    twitter: {
      card: 'summary_large_image',
      site: '@docsgptai',
      title,
      description,
      images: [OG_IMAGE],
    },
  };
}

/**
 * Drops the emoji the sidebar titles open with.
 *
 * @param {unknown} title A sidebar title.
 * @returns {string | undefined} The plain text, or undefined when the title is not a string.
 */
function plainTitle(title) {
  if (typeof title !== 'string') return undefined;
  return title.replace(/[\p{Extended_Pictographic}\u{FE0F}\u{200D}]/gu, '').trim() || undefined;
}

/**
 * The page's JSON-LD: the docs WebSite on the home page; a TechArticle and its
 * BreadcrumbList everywhere else.
 *
 * @param {object} args
 * @param {string} args.route The page's route.
 * @param {Record<string, any>} args.metadata The page metadata from Nextra's importPage().
 * @param {Array<Record<string, any>>} args.activePath Nextra's activePath: the sidebar items from the top
 *   level down to this page.
 * @param {Set<string>} args.pageRoutes Every route that is a page, so breadcrumbs skip folders without one.
 * @returns {object[]} The JSON-LD objects to embed.
 */
export function structuredData({ route, metadata, activePath, pageRoutes }) {
  const url = `${SITE_URL}${route === '/' ? '/' : route}`;
  const website = {
    '@type': 'WebSite',
    '@id': WEBSITE_ID,
    name: SITE_NAME,
    url: `${SITE_URL}/`,
    inLanguage: 'en',
    publisher: PUBLISHER,
  };
  if (route === '/') {
    return [{ '@context': 'https://schema.org', ...website, description: metadata.description }];
  }

  const modified = lastUpdatedOf(metadata);
  const article = {
    '@context': 'https://schema.org',
    '@type': 'TechArticle',
    '@id': `${url}#article`,
    headline: metadata.title,
    description: metadata.description,
    url,
    mainEntityOfPage: url,
    inLanguage: 'en',
    image: `${SITE_URL}${OG_IMAGE.url}`,
    isPartOf: { '@type': 'WebSite', '@id': WEBSITE_ID, name: SITE_NAME, url: `${SITE_URL}/` },
    publisher: PUBLISHER,
    about: { '@type': 'SoftwareApplication', name: 'DocsGPT', url: 'https://www.docsgpt.cloud/' },
    ...(modified ? { dateModified: modified } : {}),
  };

  const crumbs = [{ name: SITE_NAME, item: `${SITE_URL}/` }];
  for (const step of activePath) {
    if (!step.route || step.route === '/' || step.route === route) continue;
    if (!pageRoutes.has(step.route)) continue;
    const name = plainTitle(step.title) ?? plainTitle(step.frontMatter?.title);
    if (name) crumbs.push({ name, item: `${SITE_URL}${step.route}` });
  }
  crumbs.push({ name: metadata.title, item: url });
  const breadcrumbs = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: crumbs.map((crumb, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: crumb.name,
      item: crumb.item,
    })),
  };
  return [article, breadcrumbs];
}

/**
 * JSON for a <script type="application/ld+json"> body, with "<" escaped so
 * page text can never close the script element.
 *
 * @param {object} data The JSON-LD.
 * @returns {string} The serialized JSON.
 */
export function jsonLd(data) {
  return JSON.stringify(data).replace(/</g, '\\u003c');
}
