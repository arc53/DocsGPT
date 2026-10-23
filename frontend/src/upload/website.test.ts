import type { TFunction } from 'i18next';
import { describe, expect, it } from 'vitest';

import {
  defaultWebsiteDraft,
  isQueueFailed,
  isWebsiteDraftValid,
  nameFromUrl,
  normalizeUrl,
  pageKey,
  pathPrefixFromUrl,
  tooManyPages,
  websiteConfig,
  websiteRefusal,
} from './website';

describe('normalizeUrl', () => {
  it('adds https:// to a bare host and trims', () => {
    expect(normalizeUrl('  docs.docsgpt.cloud/Deploying ')).toBe(
      'https://docs.docsgpt.cloud/Deploying',
    );
  });

  it('keeps an http(s) address as written', () => {
    expect(normalizeUrl('http://x.io/a')).toBe('http://x.io/a');
  });

  it('rejects what is not a web address', () => {
    expect(normalizeUrl('')).toBeNull();
    expect(normalizeUrl('ftp://x.io/a')).toBeNull();
    expect(normalizeUrl('not a url')).toBeNull();
    expect(normalizeUrl('javascript:alert(1)')).toBeNull();
  });

  // The backend's validate_url refuses these, so the ingest would fail later.
  it('rejects the addresses the server never fetches', () => {
    expect(normalizeUrl('localhost:8080/docs')).toBeNull();
    expect(normalizeUrl('http://localhost/docs')).toBeNull();
    expect(normalizeUrl('http://localhost.localdomain/')).toBeNull();
    expect(normalizeUrl('http://metadata.google.internal/')).toBeNull();
    expect(normalizeUrl('http://127.0.0.1:3000/')).toBeNull();
    expect(normalizeUrl('http://10.0.0.5/')).toBeNull();
    expect(normalizeUrl('http://172.20.1.1/')).toBeNull();
    expect(normalizeUrl('http://192.168.1.10/')).toBeNull();
    expect(normalizeUrl('http://169.254.169.254/latest')).toBeNull();
    expect(normalizeUrl('http://100.64.0.1/')).toBeNull();
    expect(normalizeUrl('http://0.0.0.0/')).toBeNull();
    // Public addresses, numeric or not, stay.
    expect(normalizeUrl('http://8.8.8.8/')).toBe('http://8.8.8.8/');
    expect(normalizeUrl('http://172.32.0.1/')).toBe('http://172.32.0.1/');
    expect(normalizeUrl('https://localhost.dev/')).toBe(
      'https://localhost.dev/',
    );
  });

  // The server accepts these; which ones it may reach is its call.
  it('keeps a bracketed IPv6 address', () => {
    expect(normalizeUrl('http://[2001:4860:4860::8888]/docs')).toBe(
      'http://[2001:4860:4860::8888]/docs',
    );
    expect(normalizeUrl('[2606:4700::1111]:8080/a')).toBe(
      'https://[2606:4700::1111]:8080/a',
    );
    expect(normalizeUrl('http://2001:db8::1/')).toBeNull();
  });

  // website_loader's _HOST_PORT: a dotted host (or localhost) and `:digits`
  // is a host and its port, not a scheme.
  it('reads a bare host:port as a host, not a scheme', () => {
    expect(normalizeUrl('docs.x.io:8080/guide')).toBe(
      'https://docs.x.io:8080/guide',
    );
    expect(normalizeUrl('docs.x.io:8080')).toBe('https://docs.x.io:8080');
    expect(normalizeUrl('example.com:443/a')).toBe('https://example.com:443/a');
    expect(normalizeUrl('Docs.X.io:8080?a=1')).toBe(
      'https://Docs.X.io:8080?a=1',
    );
    // Still refused for what the host is.
    expect(normalizeUrl('localhost:3000/docs')).toBeNull();
    expect(normalizeUrl('192.168.1.10:8080/wiki')).toBeNull();
    // A scheme stays a scheme.
    expect(normalizeUrl('mailto:me@x.io')).toBeNull();
    expect(normalizeUrl('https://docs.x.io:8080/a')).toBe(
      'https://docs.x.io:8080/a',
    );
  });

  // The server refuses these too (is_web_address).
  it('refuses credentials, control characters and malformed hosts', () => {
    expect(normalizeUrl('https://user:pass@docs.x.io/a')).toBeNull();
    expect(normalizeUrl('user@docs.x.io/a')).toBeNull();
    expect(normalizeUrl('https://@docs.x.io/a')).toBeNull();
    expect(normalizeUrl('https://docs.x.io/a\u0000b')).toBeNull();
    expect(normalizeUrl('https://docs.x.io/a\tb')).toBeNull();
    expect(normalizeUrl('https://docs.x.io/a\u007fb')).toBeNull();
    expect(normalizeUrl('https://docs x.io/a')).toBeNull();
    expect(normalizeUrl('https://a..b.com/')).toBeNull();
    expect(normalizeUrl('https://.docs.x.io/')).toBeNull();
    expect(normalizeUrl(`https://${'a'.repeat(64)}.com/`)).toBeNull();
    // A label of 63 is fine, and so is the root's trailing dot.
    expect(normalizeUrl(`https://${'a'.repeat(63)}.com/`)).toBe(
      `https://${'a'.repeat(63)}.com/`,
    );
    expect(normalizeUrl('https://docs.x.io./a')).toBe('https://docs.x.io./a');
    // An @ in the path or query is not a credential.
    expect(normalizeUrl('https://docs.x.io/@team?by=a@b')).toBe(
      'https://docs.x.io/@team?by=a@b',
    );
  });

  // URL finds a host in each; the server's urlsplit doesn't.
  it('refuses anything but scheme:// before the host, and a backslash in it', () => {
    expect(normalizeUrl('https:/x.io/a')).toBeNull();
    expect(normalizeUrl('https:x.io/a')).toBeNull();
    expect(normalizeUrl('https:///x.io')).toBeNull();
    expect(normalizeUrl('https:\\\\x.io/a')).toBeNull();
    expect(normalizeUrl('https://x.io\\a')).toBeNull();
    expect(normalizeUrl('///x.io/a')).toBeNull();
  });

  it('takes a scheme-relative address as https', () => {
    expect(normalizeUrl('//x.io/a')).toBe('https://x.io/a');
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

  it('sends each "This page" address once, keeping the first spelling', () => {
    const draft = {
      ...defaultWebsiteDraft(100),
      urls: [
        'https://docs.x.io/a',
        'http://www.docs.x.io/a/',
        'https://docs.x.io/b',
        'docs.x.io/docs/../a',
      ],
    };

    expect(websiteConfig(draft, false).entries).toEqual([
      { url: 'https://docs.x.io/a', mode: 'page' },
      { url: 'https://docs.x.io/b', mode: 'page' },
    ]);
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

describe('pageKey', () => {
  it('treats scheme, www., a trailing slash and the fragment as the same page', () => {
    const key = pageKey('https://docs.x.io/guide');
    expect(pageKey('http://www.docs.x.io/guide/')).toBe(key);
    expect(pageKey('https://DOCS.x.io/guide#install')).toBe(key);
    expect(pageKey('https://docs.x.io/guides')).not.toBe(key);
    expect(pageKey('https://docs.x.io/guide?v=2')).not.toBe(key);
  });

  // The backend's own keys for these (website_loader.page_key, run on each).
  it.each([
    ['https://docs.x.io/guide', 'docs.x.io/guide'],
    ['http://www.docs.x.io/guide/', 'docs.x.io/guide'],
    ['https://DOCS.x.io/guide#install', 'docs.x.io/guide'],
    ['https://docs.x.io./guide', 'docs.x.io/guide'],
    ['https://www.docs.x.io../guide//', 'docs.x.io/guide'],
    ['https://docs.x.io/p?b=2&a=1', 'docs.x.io/p?a=1&b=2'],
    ['https://docs.x.io/p?a=1&b=2#top', 'docs.x.io/p?a=1&b=2'],
    ['https://docs.x.io/p?flag', 'docs.x.io/p?flag='],
    ['https://docs.x.io/p?a=1&&b=', 'docs.x.io/p?a=1&b='],
    ['https://docs.x.io/p?q=a+b&r=%7E~*', 'docs.x.io/p?q=a+b&r=~~%2A'],
    ['https://docs.x.io/p?z=1&a=2&a=1', 'docs.x.io/p?a=1&a=2&z=1'],
    ['https://docs.x.io/p?', 'docs.x.io/p'],
    ['https://user:pw@Docs.X.io:8080/Guide/', 'docs.x.io:8080/Guide'],
    // A port counts unless it is the scheme's default.
    ['https://x.io:8443/a', 'x.io:8443/a'],
    ['https://x.io:443/a', 'x.io/a'],
    ['http://x.io:80/a', 'x.io/a'],
    ['http://x.io:443/a', 'x.io:443/a'],
    ['https://x.io:80/a', 'x.io:80/a'],
    // An IPv6 host keeps its brackets, port or not.
    ['https://[2001:DB8::1]:8443/a', '[2001:db8::1]:8443/a'],
    ['https://[2001:db8::1]/a', '[2001:db8::1]/a'],
    // Dot segments resolve, a percent-encoded dot too; only whole segments.
    ['https://x.io/docs/../a', 'x.io/a'],
    ['https://x.io/docs/./a', 'x.io/docs/a'],
    ['https://x.io/docs/%2e%2E/a', 'x.io/a'],
    ['https://x.io/docs/%2E/a', 'x.io/docs/a'],
    ['https://x.io/../../a', 'x.io/a'],
    ['https://x.io/a/b/..', 'x.io/a'],
    ['https://x.io/a..b/c', 'x.io/a..b/c'],
    ['https://x.io/docs/../a?b=2&a=1', 'x.io/a?a=1&b=2'],
    ['https://docs.x.io', 'docs.x.io'],
    ['https://docs.x.io/A%20B/', 'docs.x.io/A%20B'],
    ['  https://docs.x.io/trim  ', 'docs.x.io/trim'],
    [
      'https://docs.x.io/p?name=caf%C3%A9&x=(1)',
      'docs.x.io/p?name=caf%C3%A9&x=%281%29',
    ],
    // The path's percent-encoding: non-ASCII, spaces and control characters
    // encoded, an unreserved character decoded, any other hex in capitals;
    // an encoded slash stays encoded.
    ['https://x.io/café', 'x.io/caf%C3%A9'],
    ['https://x.io/caf%C3%A9', 'x.io/caf%C3%A9'],
    ['https://x.io/caf%c3%a9', 'x.io/caf%C3%A9'],
    ['https://x.io/a~b', 'x.io/a~b'],
    ['https://x.io/a%7Eb', 'x.io/a~b'],
    ['https://x.io/a%7eb', 'x.io/a~b'],
    ['https://x.io/a b', 'x.io/a%20b'],
    ['https://x.io/a%20b', 'x.io/a%20b'],
    ['https://x.io/%70rivate/', 'x.io/private'],
    ['https://x.io/docs/..%2Fadmin', 'x.io/docs/..%2Fadmin'],
    ['https://x.io/docs/..%2fadmin', 'x.io/docs/..%2Fadmin'],
    ['https://x.io/a%2Eb', 'x.io/a.b'],
    ['https://x.io/a%zz', 'x.io/a%zz'],
    // The host in its ASCII (IDNA) form.
    ['https://bücher.de/a', 'xn--bcher-kva.de/a'],
    ['https://xn--bcher-kva.de/a', 'xn--bcher-kva.de/a'],
    ['https://www.Bücher.de:8080/a', 'xn--bcher-kva.de:8080/a'],
    // ASCII first, then www. and trailing dots, as the backend's bare_host.
    ['https://ｗｗｗ.x.io/a', 'x.io/a'],
    ['https://x.io\u3002/a', 'x.io/a'],
    ['https://ＷＷＷ.Ｘ.ＩＯ/a', 'x.io/a'],
    // A label IDNA2008 refuses keeps the host as given (lower-cased).
    ['https://😀.ws/', '😀.ws'],
    ['https://www.😀.ws/a', '😀.ws/a'],
    ['https://☃.net/', '☃.net'],
    ['https://ü-.de/', 'ü-.de'],
    ['https://a\u05d0.com/', 'a\u05d0.com'],
    ['https://\u0661\u0662.com/', '\u0661\u0662.com'],
    // ...and one it takes is encoded, a middle dot between two ls too.
    ['https://l\u00b7l.com/', 'xn--ll-0ea.com'],
    ['https://пример.рф/', 'xn--e1afmkfd.xn--p1ai'],
    // A label typed in punycode stays as written.
    ['https://xn--e28h.bücher.de/a', 'xn--e28h.xn--bcher-kva.de/a'],
  ])('keys %s as the backend does', (url, key) => {
    expect(pageKey(url)).toBe(key);
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
