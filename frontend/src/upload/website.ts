/**
 * The Website source form's draft and the config it sends to /api/remote
 * (`source=website`). A draft is either "This page" (one or more addresses,
 * each fetched as written) or "Whole site" (one start address and its scope).
 */

export type WebsiteMode = 'page' | 'site';
export type WebsiteDiscovery = 'auto' | 'sitemap' | 'links';
export type SyncFrequency = 'never' | 'daily' | 'weekly' | 'monthly';

export const SYNC_FREQUENCIES: SyncFrequency[] = [
  'never',
  'daily',
  'weekly',
  'monthly',
];

export type WebsiteDraft = {
  mode: WebsiteMode;
  /** "This page" uses every address; "Whole site" the first. */
  urls: string[];
  maxPages: number;
  pathPrefix: string;
  includeSubdomains: boolean;
  discovery: WebsiteDiscovery;
  sitemapUrl: string;
};

export type WebsiteEntry = {
  url: string;
  mode: WebsiteMode;
  max_pages?: number;
  path_prefix?: string;
  include_subdomains?: boolean;
  discovery?: WebsiteDiscovery;
  sitemap_url?: string;
};

export type WebsiteConfig = {
  entries: WebsiteEntry[];
  skip: string[];
  keep_links: boolean;
};

/** The page limit and its cap when /api/config doesn't say (WEB_DEFAULT_PAGES, WEB_MAX_PAGES). */
export const DEFAULT_WEB_PAGES = 100;
export const MAX_WEB_PAGES = 100;

export function defaultWebsiteDraft(defaultPages: number): WebsiteDraft {
  return {
    mode: 'page',
    urls: [''],
    maxPages: defaultPages,
    pathPrefix: '',
    includeSubdomains: false,
    discovery: 'auto',
    sitemapUrl: '',
  };
}

/**
 * A typed address as a fetchable URL: trimmed, `https://` added to a bare
 * host, anything but http(s) refused.
 */
export function normalizeUrl(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const withScheme = /^[a-z][a-z0-9+.-]*:/i.test(trimmed)
    ? trimmed
    : `https://${trimmed}`;
  try {
    const url = new URL(withScheme);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    if (!url.hostname.includes('.') && url.hostname !== 'localhost')
      return null;
    return withScheme;
  } catch {
    return null;
  }
}

function parse(value: string): URL | null {
  const normalized = normalizeUrl(value);
  return normalized ? new URL(normalized) : null;
}

/** The name a source gets from its address until the user types one: the host. */
export function nameFromUrl(value: string): string {
  const url = parse(value);
  return url ? url.hostname.replace(/^www\./, '') : '';
}

/** "Stay under" filled from an address that ends in a folder (`/Deploying/`). */
export function pathPrefixFromUrl(value: string): string {
  const url = parse(value);
  if (!url || url.pathname === '/' || !url.pathname.endsWith('/')) return '';
  return url.pathname;
}

/**
 * One key per page, as the backend compares them (`website_loader.page_key`):
 * scheme, `www.`, the host's case, a trailing slash and the fragment don't
 * count; the query does.
 */
export function pageKey(value: string): string {
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase().replace(/^www\./, '');
    const path = url.pathname.replace(/\/+$/, '');
    return `${host}${path}${url.search}`;
  } catch {
    return value.trim();
  }
}

export function websiteConfig(
  draft: WebsiteDraft,
  keepLinks: boolean,
): WebsiteConfig {
  const urls = draft.urls
    .map(normalizeUrl)
    .filter((url): url is string => !!url);
  let entries: WebsiteEntry[];
  if (draft.mode === 'page') {
    entries = urls.map((url) => ({ url, mode: 'page' }));
  } else {
    const entry: WebsiteEntry = {
      url: urls[0],
      mode: 'site',
      max_pages: draft.maxPages,
      path_prefix: draft.pathPrefix.trim(),
      include_subdomains: draft.includeSubdomains,
      discovery: draft.discovery,
    };
    const sitemapUrl = normalizeUrl(draft.sitemapUrl);
    if (draft.discovery === 'sitemap' && sitemapUrl)
      entry.sitemap_url = sitemapUrl;
    entries = urls.length ? [entry] : [];
  }
  return { entries, skip: [], keep_links: keepLinks };
}

export function isWebsiteDraftValid(
  draft: WebsiteDraft,
  maxPages: number,
): boolean {
  const filled = (draft.mode === 'page' ? draft.urls : draft.urls.slice(0, 1))
    .map((url) => url.trim())
    .filter(Boolean);
  if (!filled.length || filled.some((url) => !normalizeUrl(url))) return false;
  if (draft.mode === 'site') {
    if (
      !Number.isInteger(draft.maxPages) ||
      draft.maxPages < 1 ||
      draft.maxPages > maxPages
    )
      return false;
    if (draft.discovery === 'sitemap' && draft.sitemapUrl.trim())
      return !!normalizeUrl(draft.sitemapUrl);
  }
  return true;
}
