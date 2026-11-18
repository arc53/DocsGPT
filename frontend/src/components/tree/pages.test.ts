import { describe, expect, it } from 'vitest';

import { folderAddress, pageAddress, withPageTitles } from './pages';
import type { FileNode } from './types';

const leaf = (extra: Record<string, unknown> = {}) => ({
  type: 'text/markdown',
  size_bytes: 10,
  token_count: 5,
  ...extra,
});

describe('withPageTitles', () => {
  it('names a web page by its title, keeping folders and other files', () => {
    const structure = {
      'index.md': leaf({ url: 'https://x.io/', title: 'Home' }),
      Deploying: {
        'Docker.md': leaf({
          url: 'https://x.io/Deploying/Docker',
          title: 'Docker',
        }),
      },
      'notes.md': leaf(),
      'named.md': leaf({
        url: 'https://x.io/n',
        title: 'T',
        display_name: 'Kept',
      }),
    };

    const result = withPageTitles(structure);

    expect(result['index.md'].display_name).toBe('Home');
    expect(
      (result.Deploying as unknown as Record<string, FileNode>)['Docker.md']
        .display_name,
    ).toBe('Docker');
    expect(result['notes.md'].display_name).toBeUndefined();
    expect(result['named.md'].display_name).toBe('Kept');
    // The input is left alone.
    expect(
      (structure['index.md'] as Record<string, unknown>).display_name,
    ).toBeUndefined();
  });
});

describe('withPageTitles, site suffix', () => {
  it('drops a site name every page title ends with', () => {
    const result = withPageTitles({
      'a.md': leaf({
        url: 'https://x.io/a',
        title: 'Security Checklist | DocsGPT Docs',
      }),
      dir: {
        'b.md': leaf({
          url: 'https://x.io/b',
          title: 'Air-Gapped Deployment | DocsGPT Docs',
        }),
      },
    });

    expect(result['a.md'].display_name).toBe('Security Checklist');
    expect(
      (result.dir as unknown as Record<string, FileNode>)['b.md'].display_name,
    ).toBe('Air-Gapped Deployment');
  });

  it('keeps titles whole when the pages do not share a suffix, or there is one page', () => {
    const mixed = withPageTitles({
      'a.md': leaf({ url: 'https://x.io/a', title: 'Intro | DocsGPT Docs' }),
      'b.md': leaf({ url: 'https://y.io/b', title: 'README - GitHub' }),
    });
    const single = withPageTitles({
      'a.md': leaf({ url: 'https://x.io/a', title: 'Intro | DocsGPT Docs' }),
    });

    expect(mixed['a.md'].display_name).toBe('Intro | DocsGPT Docs');
    expect(single['a.md'].display_name).toBe('Intro | DocsGPT Docs');
  });
});

describe('folderAddress', () => {
  it('is the section address a folder stands for', () => {
    const structure = {
      Deploying: {
        'Docker.md': leaf({ url: 'https://docs.x.io/Deploying/Docker' }),
      },
      'docs.x.io': {
        API: { 'a.md': leaf({ url: 'https://docs.x.io/API/a' }) },
      },
    };

    expect(folderAddress(structure, 'Deploying')).toBe('docs.x.io/Deploying/');
    // In a source with several hosts the first folder is the host.
    expect(folderAddress(structure, 'docs.x.io/API')).toBe('docs.x.io/API/');
    expect(folderAddress(structure, 'docs.x.io')).toBe('docs.x.io/');
    expect(folderAddress(structure, 'Missing')).toBeNull();
  });
});

describe('pageAddress', () => {
  it('shows an address without its scheme or trailing slash', () => {
    expect(pageAddress('https://docs.docsgpt.cloud/upgrading/')).toBe(
      'docs.docsgpt.cloud/upgrading',
    );
    expect(pageAddress('https://docs.docsgpt.cloud/')).toBe(
      'docs.docsgpt.cloud',
    );
    expect(pageAddress('https://x.io/list?page=2')).toBe('x.io/list?page=2');
  });
});
