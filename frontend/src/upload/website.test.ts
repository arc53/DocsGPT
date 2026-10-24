import type { TFunction } from 'i18next';
import { describe, expect, it } from 'vitest';

import {
  defaultWebsiteDraft,
  isQueueFailed,
  isWebsiteDraftValid,
  nameFromUrl,
  normalizeUrl,
  pathPrefixFromUrl,
  tooManyPages,
  websiteConfig,
  websiteRefusal,
} from './website';

describe('normalizeUrl', () => {
  it.each([
    // A bare host gets https://, and the address is trimmed.
    ['  docs.docsgpt.cloud/Deploying ', 'https://docs.docsgpt.cloud/Deploying'],
    ['http://x.io/a', 'http://x.io/a'],
    ['//x.io/a', 'https://x.io/a'],
    // Public addresses, numeric or not.
    ['http://8.8.8.8/', 'http://8.8.8.8/'],
    ['http://172.32.0.1/', 'http://172.32.0.1/'],
    ['https://localhost.dev/', 'https://localhost.dev/'],
    // A bracketed IPv6 address: which ones the server may reach is its call.
    [
      'http://[2001:4860:4860::8888]/docs',
      'http://[2001:4860:4860::8888]/docs',
    ],
    ['[2606:4700::1111]:8080/a', 'https://[2606:4700::1111]:8080/a'],
    // A bare host:port is a host and its port, not a scheme (_HOST_PORT).
    ['docs.x.io:8080/guide', 'https://docs.x.io:8080/guide'],
    ['docs.x.io:8080', 'https://docs.x.io:8080'],
    ['example.com:443/a', 'https://example.com:443/a'],
    ['Docs.X.io:8080?a=1', 'https://Docs.X.io:8080?a=1'],
    ['https://docs.x.io:8080/a', 'https://docs.x.io:8080/a'],
    // A label of 63 is fine, and so is the root's trailing dot.
    [`https://${'a'.repeat(63)}.com/`, `https://${'a'.repeat(63)}.com/`],
    ['https://docs.x.io./a', 'https://docs.x.io./a'],
    // An @ in the path or query is not a credential.
    ['https://docs.x.io/@team?by=a@b', 'https://docs.x.io/@team?by=a@b'],
  ])('takes %j as %j', (value, url) => {
    expect(normalizeUrl(value)).toBe(url);
  });

  it.each([
    // Not a web address.
    '',
    'ftp://x.io/a',
    'not a url',
    'javascript:alert(1)',
    'mailto:me@x.io',
    // Hosts the backend's validate_url never fetches.
    'localhost:8080/docs',
    'localhost:3000/docs',
    'http://localhost/docs',
    'http://localhost.localdomain/',
    'http://metadata.google.internal/',
    'http://127.0.0.1:3000/',
    'http://10.0.0.5/',
    'http://172.20.1.1/',
    'http://192.168.1.10/',
    '192.168.1.10:8080/wiki',
    'http://169.254.169.254/latest',
    'http://100.64.0.1/',
    'http://0.0.0.0/',
    'http://2001:db8::1/',
    // Credentials, control characters and malformed hosts (is_web_address).
    'https://user:pass@docs.x.io/a',
    'user@docs.x.io/a',
    'https://@docs.x.io/a',
    'https://docs.x.io/a\u0000b',
    'https://docs.x.io/a\tb',
    'https://docs.x.io/a\u007fb',
    'https://docs x.io/a',
    'https://a..b.com/',
    'https://.docs.x.io/',
    `https://${'a'.repeat(64)}.com/`,
    // URL finds a host in these; the server's urlsplit doesn't.
    'https:/x.io/a',
    'https:x.io/a',
    'https:///x.io',
    'https:\\\\x.io/a',
    'https://x.io\\a',
    '///x.io/a',
  ])('refuses %j', (value) => {
    expect(normalizeUrl(value)).toBeNull();
  });
});

describe('nameFromUrl', () => {
  it('names a source after the host, without www.', () => {
    expect(nameFromUrl('https://www.docsgpt.cloud/blog')).toBe('docsgpt.cloud');
    expect(nameFromUrl('nonsense')).toBe('');
  });
});

describe('pathPrefixFromUrl', () => {
  it('fills "Stay under" from an address that ends in a folder', () => {
    expect(pathPrefixFromUrl('https://docs.x.io/Deploying/')).toBe(
      '/Deploying/',
    );
  });

  it('leaves it empty for the site root or a page', () => {
    expect(pathPrefixFromUrl('https://docs.x.io/')).toBe('');
    expect(pathPrefixFromUrl('https://docs.x.io/Deploying/Docker')).toBe('');
    expect(pathPrefixFromUrl('nonsense')).toBe('');
  });
});

describe('websiteConfig', () => {
  it('turns "This page" addresses into page entries', () => {
    const draft = {
      ...defaultWebsiteDraft(100),
      urls: ['docs.x.io/a', '', 'https://docs.x.io/b'],
    };

    expect(websiteConfig(draft, false)).toEqual({
      entries: [
        { url: 'https://docs.x.io/a', mode: 'page' },
        { url: 'https://docs.x.io/b', mode: 'page' },
      ],
      skip: [],
      keep_links: false,
    });
  });

  it('turns "Whole site" into one site entry with its scope', () => {
    const draft = {
      ...defaultWebsiteDraft(100),
      mode: 'site' as const,
      urls: ['https://docs.x.io/Deploying/', 'https://ignored.io'],
      maxPages: 40,
      pathPrefix: '/Deploying/',
      includeSubdomains: true,
      discovery: 'sitemap' as const,
      sitemapUrl: 'https://docs.x.io/sitemap.xml',
    };

    expect(websiteConfig(draft, true)).toEqual({
      entries: [
        {
          url: 'https://docs.x.io/Deploying/',
          mode: 'site',
          max_pages: 40,
          path_prefix: '/Deploying/',
          include_subdomains: true,
          discovery: 'sitemap',
          sitemap_url: 'https://docs.x.io/sitemap.xml',
        },
      ],
      skip: [],
      keep_links: true,
    });
  });

  const pageUrls = (urls: string[]) =>
    websiteConfig({ ...defaultWebsiteDraft(100), urls }, false).entries.map(
      (entry) => entry.url,
    );

  // Folds the server's page_key surely makes too.
  it.each([
    ['http://www.docs.x.io/a/', 'https://docs.x.io/a'],
    ['https://DOCS.X.io/a#install', 'https://docs.x.io/a'],
    ['https://docs.x.io./a//', 'https://docs.x.io/a'],
    ['https://docs.x.io:443/a', 'https://docs.x.io/a'],
    ['http://docs.x.io:80/a', 'https://docs.x.io/a'],
    ['https://docs.x.io:0443/a', 'https://docs.x.io/a'],
    ['https://docs.x.io/a/?v=2', 'https://docs.x.io/a?v=2'],
    ['https://[2001:DB8::1]:443/a', 'https://[2001:db8::1]/a'],
  ])('sends %j once with %j, keeping the first', (later, first) => {
    expect(pageUrls([first, later, 'https://docs.x.io/b'])).toEqual([
      first,
      'https://docs.x.io/b',
    ]);
  });

  // Folds it might not make: the server dedupes those, so the form never
  // counts fewer pages than the server.
  it.each([
    ['https://docs.x.io/A', 'https://docs.x.io/a'],
    ['https://docs.x.io:8443/a', 'https://docs.x.io/a'],
    ['http://docs.x.io:443/a', 'https://docs.x.io/a'],
    ['https://docs.x.io/a?v=2', 'https://docs.x.io/a'],
    ['https://docs.x.io/p?b=2&a=1', 'https://docs.x.io/p?a=1&b=2'],
    ['https://docs.x.io/docs/../a', 'https://docs.x.io/a'],
    ['https://docs.x.io/caf%C3%A9', 'https://docs.x.io/café'],
    ['https://docs.x.io/?q=%EF%BB%BFabc', 'https://docs.x.io/?q=abc'],
    ['https://ＤＯＣＳ.x.io/a', 'https://docs.x.io/a'],
    ['https://[2001:db8::1]:8443/a', 'https://[2001:db8::1]/a'],
    // A zero-padded port is its number: the default of one scheme, not the other.
    ['https://docs.x.io:0443/a', 'http://docs.x.io:0443/a'],
    ['https://docs.x.io:080/a', 'http://docs.x.io:080/a'],
  ])('keeps %j apart from %j', (later, first) => {
    expect(pageUrls([first, later])).toEqual([first, later]);
  });

  it('sends a sitemap URL only when pages are found through the sitemap', () => {
    const draft = {
      ...defaultWebsiteDraft(100),
      mode: 'site' as const,
      urls: ['https://docs.x.io/'],
      sitemapUrl: 'https://docs.x.io/sitemap.xml',
    };

    expect(websiteConfig(draft, false).entries[0]).not.toHaveProperty(
      'sitemap_url',
    );
  });
});

describe('isWebsiteDraftValid', () => {
  it('needs at least one web address', () => {
    expect(isWebsiteDraftValid(defaultWebsiteDraft(100), 500)).toBe(false);
    expect(
      isWebsiteDraftValid(
        { ...defaultWebsiteDraft(100), urls: ['docs.x.io'] },
        500,
      ),
    ).toBe(true);
  });

  it('rejects an address that is not a web address', () => {
    expect(
      isWebsiteDraftValid(
        { ...defaultWebsiteDraft(100), urls: ['https://x.io', 'ftp://x.io'] },
        500,
      ),
    ).toBe(false);
  });

  it('keeps the page limit within the admin cap', () => {
    const site = {
      ...defaultWebsiteDraft(100),
      mode: 'site' as const,
      urls: ['https://x.io'],
    };
    expect(isWebsiteDraftValid({ ...site, maxPages: 500 }, 500)).toBe(true);
    expect(isWebsiteDraftValid({ ...site, maxPages: 501 }, 500)).toBe(false);
    expect(isWebsiteDraftValid({ ...site, maxPages: 0 }, 500)).toBe(false);
  });

  it('holds no more page addresses than the cap', () => {
    const pages = (count: number) => ({
      ...defaultWebsiteDraft(2),
      urls: [
        ...Array.from({ length: count }, (_, i) => `https://x.io/${i}`),
        '',
      ],
    });
    expect(isWebsiteDraftValid(pages(2), 2)).toBe(true);
    expect(isWebsiteDraftValid(pages(3), 2)).toBe(false);
    expect(tooManyPages(pages(3), 2)).toBe(true);
    expect(tooManyPages(pages(2), 2)).toBe(false);
    // The same page twice counts once, as it is sent once.
    expect(
      tooManyPages(
        { ...pages(2), urls: ['https://x.io/0', 'x.io/0/', 'https://x.io/1'] },
        2,
      ),
    ).toBe(false);
    // A whole site uses only its first address.
    expect(tooManyPages({ ...pages(3), mode: 'site' }, 2)).toBe(false);
  });
});

describe('isQueueFailed', () => {
  it('knows a change saved but not queued by its code', () => {
    expect(isQueueFailed({ success: false, code: 'queue_failed' })).toBe(true);
    expect(isQueueFailed({ success: false, code: 'wiki' })).toBe(false);
    expect(isQueueFailed(null)).toBe(false);
    expect(isQueueFailed('queue_failed')).toBe(false);
  });
});

describe('websiteRefusal', () => {
  const t = ((key: string, opts?: Record<string, unknown>) =>
    opts ? `${key} ${JSON.stringify(opts)}` : key) as unknown as TFunction;
  const key = (name: string) => `settings.sources.website.${name}`;

  it('words the codes the UI knows', () => {
    expect(websiteRefusal(t, 400, { code: 'wiki', error: 'x' })).toBe(
      key('wikiSource'),
    );
    expect(
      websiteRefusal(t, 400, { code: 'chunks_unsupported', error: 'x' }),
    ).toBe(key('chunksUnsupported'));
    expect(websiteRefusal(t, 400, { code: 'last_entry', error: 'x' })).toBe(
      key('removeLast'),
    );
    expect(websiteRefusal(t, 400, { code: 'page_limit', max_pages: 100 })).toBe(
      `${key('pageLimit')} {"count":100}`,
    );
  });

  it.each([
    ['site_limit', { max_sites: 20 }, 'siteLimit {"count":20}'],
    ['skip_limit', { max_skip: 1000 }, 'skipLimit {"count":1000}'],
    ['url_too_long', { max_length: 2048 }, 'urlTooLong {"count":2048}'],
    ['invalid_config', {}, 'invalidConfig'],
    ['not_found', {}, 'notFound'],
    ['bad_sync_frequency', {}, 'badSyncFrequency'],
    ['too_many_paths', { max_paths: 500 }, 'tooManyPaths {"count":500}'],
    ['not_website', {}, 'notWebsite'],
    ['queue_failed', { message: 'Saved, not queued' }, 'queueFailed'],
    // The UI never builds these; one line covers them.
    ['invalid_body', {}, 'badRequest'],
    ['missing_fields', { fields: ['source_id'] }, 'badRequest'],
    ['invalid_field', { field: 'entries' }, 'badRequest'],
  ])('words %s with its details', (code, details, worded) => {
    expect(websiteRefusal(t, 400, { code, error: 'English', ...details })).toBe(
      key(worded),
    );
  });

  it('names the address it refused', () => {
    expect(
      websiteRefusal(t, 400, {
        code: 'invalid_address',
        url: 'http://x.io/a',
        error: 'English',
      }),
    ).toBe(
      `${key('invalidAddress')} {"url":"http://x.io/a","interpolation":{"escapeValue":false}}`,
    );
  });

  it("falls back to the server's message when a code lacks its detail", () => {
    expect(
      websiteRefusal(t, 400, { code: 'site_limit', error: 'Up to 20 sites' }),
    ).toBe('Up to 20 sites');
    expect(
      websiteRefusal(t, 400, { code: 'invalid_address', error: 'Bad address' }),
    ).toBe('Bad address');
  });

  it("shows the server's message for any other 400", () => {
    expect(
      websiteRefusal(t, 400, {
        success: false,
        error: 'The skip list holds up to 1000 rules',
      }),
    ).toBe('The skip list holds up to 1000 rules');
    expect(websiteRefusal(t, 400, { code: 'other', error: 'Bad entry' })).toBe(
      'Bad entry',
    );
  });

  it('leaves the rest to the caller', () => {
    expect(websiteRefusal(t, 400, { success: false })).toBeNull();
    expect(websiteRefusal(t, 400, { error: '   ' })).toBeNull();
    expect(websiteRefusal(t, 500, { error: 'Traceback' })).toBeNull();
    expect(websiteRefusal(t, 403, { error: 'Forbidden' })).toBeNull();
    expect(websiteRefusal(t, 400, null)).toBeNull();
    expect(websiteRefusal(t, 400, 'oops')).toBeNull();
  });
});
