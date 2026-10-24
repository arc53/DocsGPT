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
 * A bare `host:port` (`docs.x.io:8080/guide`): a dotted host or localhost,
 * then `:digits`. The server reads it as a host and its port, not a scheme
 * (website_loader's `_HOST_PORT`).
 */
const HOST_PORT = /^(?:[^:/?#@\s.]*\.[^:/?#@\s]*|localhost):\d+(?:[/?#]|$)/i;

/** Control characters (C0 and DEL), which no fetchable address holds. */
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/;

/** The longest DNS label. */
const MAX_LABEL_LENGTH = 63;

/**
 * Whether a host name has an empty label (`a..b.com`, `.x.io`) or one longer
 * than DNS allows. The root's trailing dot (`docs.x.io.`) is fine.
 */
function hasBadLabel(host: string): boolean {
  return host
    .replace(/\.$/, '')
    .split('.')
    .some((label) => !label || label.length > MAX_LABEL_LENGTH);
}

/**
 * A scheme and exactly two slashes, then the host: `https:/x.io`,
 * `https:x.io` and `https:///x.io` have no host as the server reads them
 * (`urlsplit`), though `URL` finds one.
 */
const SCHEME_AND_AUTHORITY = /^[a-z][a-z0-9+.-]*:\/\/(?!\/)([^/?#]*)/i;

/**
 * A typed address as a fetchable URL: trimmed, `https://` added to a bare
 * host (`host:port` included) and `https:` to a scheme-relative one
 * (`//x.io/a`), anything but http(s) refused, and so is a host the backend
 * refuses to fetch (localhost, a private or reserved IPv4 address) and what
 * it can't parse as one: anything but `scheme://` before the host,
 * credentials (`user:pass@`), control characters, whitespace or a backslash
 * in the host, an empty or over-long label. A bracketed IPv6 address is
 * kept; the backend decides which of those it may reach.
 */
export function normalizeUrl(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed || CONTROL_CHARS.test(trimmed)) return null;
  const withScheme = /^\/\/(?!\/)/.test(trimmed)
    ? `https:${trimmed}`
    : /^[a-z][a-z0-9+.-]*:/i.test(trimmed) && !HOST_PORT.test(trimmed)
      ? trimmed
      : `https://${trimmed}`;
  try {
    const url = new URL(withScheme);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    // The authority as written: URL drops an empty `@`, maps some spaces
    // and reads a backslash as a slash.
    const authority = SCHEME_AND_AUTHORITY.exec(withScheme)?.[1];
    if (
      !authority ||
      authority.includes('@') ||
      authority.includes('\\') ||
      /\s/.test(authority)
    )
      return null;
    const host = url.hostname.toLowerCase();
    const ipv6 = host.startsWith('[') && host.endsWith(']');
    if ((!ipv6 && !host.includes('.')) || BLOCKED_HOSTS.has(host)) return null;
    if (!ipv6 && hasBadLabel(host)) return null;
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

/** The port each scheme uses when an address names none. */
const DEFAULT_PORTS: Record<string, string> = { http: '80', https: '443' };

/**
 * A key for telling the form's addresses apart: a normalized address
 * (see {@link normalizeUrl}) without its scheme, fragment, `www.`, the
 * scheme's own port or a trailing slash, its host in lower case. Only folds
 * the server's page key surely makes as well, so the form never counts
 * fewer pages than the server does; the server decides the rest (a query's
 * order, percent-encoding, dot segments, an IDN host).
 */
function formKey(normalized: string): string {
  const match = /^([a-z][a-z0-9+.-]*):\/\/([^/?#]*)([^?#]*)([^#]*)/i.exec(
    normalized,
  );
  if (!match) return normalized;
  const [, scheme, authority, path, query] = match;
  // A bracketed IPv6 host keeps its colons; a port follows the last `]`.
  const at = authority.lastIndexOf(':');
  const hasPort = at > authority.lastIndexOf(']');
  // As a number, as the server reads it: `:0443` is https's own port.
  const port =
    hasPort && authority.slice(at + 1)
      ? String(Number(authority.slice(at + 1)))
      : '';
  const host = (hasPort ? authority.slice(0, at) : authority)
    // ASCII only: the server maps a non-ASCII host its own way.
    .replace(/[A-Z]+/g, (letters) => letters.toLowerCase())
    .replace(/\.+$/, '')
    .replace(/^www\./, '');
  const ownPort = !port || port === DEFAULT_PORTS[scheme.toLowerCase()];
  return `${host}${ownPort ? '' : `:${port}`}${path.replace(/\/+$/, '')}${query}`;
}

/** Addresses naming the same page (see {@link formKey}) once, the first kept. */
function uniquePages(urls: string[]): string[] {
  const seen = new Set<string>();
  return urls.filter((url) => {
    const normalized = normalizeUrl(url);
    const key = normalized ? formKey(normalized) : url;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
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
    entries = uniquePages(urls).map((url) => ({ url, mode: 'page' }));
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
 * Whether "This page" lists more pages than a source holds (WEB_MAX_PAGES;
 * the backend refuses the config). The same page written twice counts once,
 * as {@link websiteConfig} sends it once.
 */
export function tooManyPages(draft: WebsiteDraft, maxPages: number): boolean {
  return (
    draft.mode === 'page' && uniquePages(filledUrls(draft)).length > maxPages
  );
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
  // Add pages naming only what the source already fetches.
  ['already_listed', 'alreadyListed'],
  // Saved, but its task couldn't be queued: the next sync runs it.
  ['queue_failed', 'queueFailed'],
  // A body the UI never builds: one line for all three.
  ['invalid_body', 'badRequest'],
  ['missing_fields', 'badRequest'],
  ['invalid_field', 'badRequest'],
]);

/**
 * Whether a /api/website answer says the change was saved but its task
 * couldn't be queued (HTTP 500, `code: queue_failed`): the next sync runs
 * it, so it is a warning, not a failure, and retrying would repeat it.
 *
 * @param body The response's JSON, if it parsed.
 */
export function isQueueFailed(body: unknown): boolean {
  return (
    !!body &&
    typeof body === 'object' &&
    (body as Record<string, unknown>).code === 'queue_failed'
  );
}

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
