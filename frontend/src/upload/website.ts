/**
 * The Website source form's draft and the config it sends to /api/remote
 * (`source=website`). A draft is either "This page" (one or more addresses,
 * each fetched as written) or "Whole site" (one start address and its scope).
 */

import type { TFunction } from 'i18next';

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

// Hosts the backend's validate_url refuses by name (url_validation.py).
const BLOCKED_HOSTS = new Set([
  'localhost',
  'localhost.localdomain',
  'metadata.google.internal',
]);

// The IPv4 ranges it refuses (private, loopback, link-local, carrier-grade
// NAT, reserved, multicast), as [first octets, prefix length].
const BLOCKED_IPV4: [number[], number][] = [
  [[0], 8],
  [[10], 8],
  [[100, 64], 10],
  [[127], 8],
  [[169, 254], 16],
  [[172, 16], 12],
  [[192, 0, 0], 24],
  [[192, 0, 2], 24],
  [[192, 168], 16],
  [[198, 18], 15],
  [[198, 51, 100], 24],
  [[203, 0, 113], 24],
  [[224], 3],
];

/** Whether a host is an IPv4 address on a network the server won't reach. */
function isBlockedIpv4(host: string): boolean {
  const match = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!match) return false;
  const value = match
    .slice(1)
    .reduce((total, octet) => total * 256 + Number(octet), 0);
  return BLOCKED_IPV4.some(([octets, bits]) => {
    const base = [0, 1, 2, 3].reduce(
      (total, i) => total * 256 + (octets[i] ?? 0),
      0,
    );
    const size = 2 ** (32 - bits);
    return Math.floor(value / size) === Math.floor(base / size);
  });
}

/**
 * A typed address as a fetchable URL: trimmed, `https://` added to a bare
 * host, anything but http(s) refused, and so is a host the backend refuses
 * to fetch (localhost, a private or reserved IPv4 address). A bracketed IPv6
 * address is kept; the backend decides which of those it may reach.
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
    const host = url.hostname.toLowerCase();
    const ipv6 = host.startsWith('[') && host.endsWith(']');
    if ((!ipv6 && !host.includes('.')) || BLOCKED_HOSTS.has(host)) return null;
    if (isBlockedIpv4(host)) return null;
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

/** Python's `unquote_plus`: `+` is a space, runs of `%XX` are UTF-8 bytes. */
function unquotePlus(value: string): string {
  return value.replace(/\+/g, ' ').replace(/(?:%[0-9a-f]{2})+/gi, (run) => {
    const bytes = new Uint8Array(run.length / 3);
    for (let i = 0; i < bytes.length; i += 1)
      bytes[i] = parseInt(run.slice(i * 3 + 1, i * 3 + 3), 16);
    return new TextDecoder().decode(bytes);
  });
}

/** Python's `quote_plus`: only letters, digits and `_.-~` stay as they are. */
function quotePlus(value: string): string {
  // A lone surrogate can't be encoded; Python replaces it too.
  const encoded = encodeURIComponent(
    value.replace(
      /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g,
      '�',
    ),
  );
  return encoded
    .replace(
      /[!'()*]/g,
      (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`,
    )
    .replace(/%20/g, '+');
}

/**
 * A query with its parameters sorted, as the backend's `normalize_page_url`
 * writes it (`urlencode(sorted(parse_qsl(query, keep_blank_values=True)))`).
 */
function sortedQuery(query: string): string {
  const pairs: [string, string][] = [];
  for (const part of query.split('&')) {
    if (!part) continue;
    const at = part.indexOf('=');
    const name = at === -1 ? part : part.slice(0, at);
    const value = at === -1 ? '' : part.slice(at + 1);
    pairs.push([unquotePlus(name), unquotePlus(value)]);
  }
  const compare = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
  pairs.sort((a, b) => compare(a[0], b[0]) || compare(a[1], b[1]));
  return pairs
    .map(([name, value]) => `${quotePlus(name)}=${quotePlus(value)}`)
    .join('&');
}

/**
 * One key per page, exactly as the backend compares them
 * (`website_loader.page_key` over `base.normalize_page_url`): the scheme,
 * `www.`, the host's case and trailing dots, a trailing slash, the fragment
 * and the order of the query's parameters don't count; the path stays as
 * written. Split the way Python's `urlsplit` does, not with `URL`, which
 * would rewrite the path.
 */
export function pageKey(value: string): string {
  let rest = value.trim();
  const scheme = /^[a-z][a-z0-9+.-]*:/i.exec(rest);
  if (scheme) rest = rest.slice(scheme[0].length);
  const hash = rest.indexOf('#');
  if (hash !== -1) rest = rest.slice(0, hash);
  let netloc = '';
  if (rest.startsWith('//')) {
    const end = rest.slice(2).search(/[/?]/);
    netloc = end === -1 ? rest.slice(2) : rest.slice(2, end + 2);
    rest = end === -1 ? '' : rest.slice(end + 2);
  }
  const mark = rest.indexOf('?');
  const path = mark === -1 ? rest : rest.slice(0, mark);
  const query = mark === -1 ? '' : sortedQuery(rest.slice(mark + 1));

  const hostinfo = netloc.slice(netloc.lastIndexOf('@') + 1);
  const bracket = hostinfo.indexOf('[');
  let host =
    bracket !== -1
      ? hostinfo.slice(bracket + 1).split(']')[0]
      : hostinfo.split(':')[0];
  host = host.toLowerCase().replace(/\.+$/, '');
  if (host.startsWith('www.')) host = host.slice(4);

  const key = `${host}${path.replace(/\/+$/, '')}`;
  return query ? `${key}?${query}` : key;
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

/** The addresses a draft fetches: every filled one, or a site's first. */
function filledUrls(draft: WebsiteDraft): string[] {
  return (draft.mode === 'page' ? draft.urls : draft.urls.slice(0, 1))
    .map((url) => url.trim())
    .filter(Boolean);
}

/**
 * Whether "This page" lists more addresses than a source holds
 * (WEB_MAX_PAGES; the backend refuses the config).
 */
export function tooManyPages(draft: WebsiteDraft, maxPages: number): boolean {
  return draft.mode === 'page' && filledUrls(draft).length > maxPages;
}

export function isWebsiteDraftValid(
  draft: WebsiteDraft,
  maxPages: number,
): boolean {
  const filled = filledUrls(draft);
  if (!filled.length || filled.some((url) => !normalizeUrl(url))) return false;
  if (tooManyPages(draft, maxPages)) return false;
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

/** Refusal codes of the /api/website routes and the website key that words each. */
const REFUSAL_KEYS = new Map<unknown, string>([
  ['wiki', 'wikiSource'],
  ['chunks_unsupported', 'chunksUnsupported'],
  ['last_entry', 'removeLast'],
  ['invalid_config', 'invalidConfig'],
  ['not_found', 'notFound'],
  ['bad_sync_frequency', 'badSyncFrequency'],
  ['not_website', 'notWebsite'],
  // A body the UI never builds: one line for all three.
  ['invalid_body', 'badRequest'],
  ['missing_fields', 'badRequest'],
  ['invalid_field', 'badRequest'],
]);

/** Codes worded with the limit the refusal names: [key, detail field]. */
const LIMIT_KEYS = new Map<unknown, [string, string]>([
  ['page_limit', ['pageLimit', 'max_pages']],
  ['site_limit', ['siteLimit', 'max_sites']],
  ['skip_limit', ['skipLimit', 'max_skip']],
  ['url_too_long', ['urlTooLong', 'max_length']],
  ['too_many_paths', ['tooManyPaths', 'max_paths']],
]);

/**
 * A refusal's `code` in the user's language, with the details it names (the
 * limit, the address), or null for a code the UI doesn't word or one that
 * came without its detail.
 *
 * @param t The translate function.
 * @param body The response's JSON, if it parsed.
 */
export function websiteRefusalForCode(
  t: TFunction,
  body: unknown,
): string | null {
  if (!body || typeof body !== 'object') return null;
  const fields = body as Record<string, unknown>;
  const { code } = fields;
  const limit = LIMIT_KEYS.get(code);
  if (limit) {
    const count = fields[limit[1]];
    return typeof count === 'number'
      ? t(`settings.sources.website.${limit[0]}`, { count })
      : null;
  }
  if (code === 'invalid_address')
    return typeof fields.url === 'string' && fields.url
      ? t('settings.sources.website.invalidAddress', {
          url: fields.url,
          interpolation: { escapeValue: false },
        })
      : null;
  const key = REFUSAL_KEYS.get(code);
  return key ? t(`settings.sources.website.${key}`) : null;
}

/**
 * What to tell the user when a /api/website route refuses a request.
 *
 * A code the UI knows is worded here (see {@link websiteRefusalForCode}).
 * Any other 400 carries the server's own message, which is shown as written
 * as a last resort.
 *
 * @param t The translate function.
 * @param status The response's HTTP status.
 * @param body The response's JSON, if it parsed.
 * @returns The message, or null when the caller's generic one fits (a
 *   server error, a 403, a body without a message).
 */
export function websiteRefusal(
  t: TFunction,
  status: number,
  body: unknown,
): string | null {
  const worded = websiteRefusalForCode(t, body);
  if (worded) return worded;
  if (!body || typeof body !== 'object') return null;
  const { error } = body as Record<string, unknown>;
  if (status === 400 && typeof error === 'string' && error.trim()) return error;
  return null;
}
