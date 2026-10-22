import { describe, expect, it } from 'vitest';

import {
  defaultWebsiteDraft,
  isWebsiteDraftValid,
  nameFromUrl,
  normalizeUrl,
  pageKey,
  pathPrefixFromUrl,
  websiteConfig,
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
});
