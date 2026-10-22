import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { state } = vi.hoisted(() => ({
  state: { structure: {} as Record<string, unknown> },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key} ${JSON.stringify(opts)}` : key,
  }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => null,
  useDispatch: () => vi.fn(),
}));

vi.mock('../hooks', () => ({
  useDarkTheme: () => [false],
  useDebouncedValue: (value: unknown) => value,
  useLoaderState: (initial: boolean) => useState(initial),
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
  useOutsideAlerter: () => undefined,
}));

vi.mock('../api/services/userService', () => ({
  default: {
    getDirectoryStructure: vi.fn(async () => ({
      json: async () => ({ directory_structure: state.structure }),
    })),
    getDocumentChunks: vi.fn(async () => ({
      ok: true,
      json: async () => ({ page: 1, per_page: 12, total: 0, chunks: [] }),
    })),
  },
}));

import WebsiteTree from './WebsiteTree';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const page = (url: string, title: string) => ({
  type: 'text/markdown',
  size_bytes: 400,
  token_count: 120,
  url,
  title,
  fetched_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
});

const SITE = {
  'index.md': page('https://docs.x.io/', 'DocsGPT'),
  Deploying: {
    'Docker.md': page(
      'https://docs.x.io/Deploying/Docker',
      'Docker Deployment',
    ),
  },
  'upgrading.md': page('https://docs.x.io/upgrading', 'Upgrading'),
};

describe('WebsiteTree', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async (
    props: Partial<React.ComponentProps<typeof WebsiteTree>> = {},
    structure: Record<string, unknown> = SITE,
  ) => {
    state.structure = structure;
    await act(async () => {
      root.render(
        <WebsiteTree
          docId="doc"
          sourceName="DocsGPT documentation (website)"
          onBackToDocuments={() => undefined}
          hosts={['docs.x.io']}
          syncFrequency="weekly"
          syncedAt={new Date().toISOString()}
          {...props}
        />,
      );
    });
  };

  it('names pages by their title, with the address under it', async () => {
    await render();
    const rows = Array.from(container.querySelectorAll('tbody tr')).map(
      (row) => row.textContent,
    );

    expect(rows.some((text) => text?.includes('Upgrading'))).toBe(true);
    expect(rows.some((text) => text?.includes('docs.x.io/upgrading'))).toBe(
      true,
    );
    expect(container.textContent).not.toContain('upgrading.md');
    expect(container.textContent).toContain('settings.sources.website.fetched');
    expect(container.textContent).not.toContain('settings.sources.size');
  });

  it('says where the source comes from and how it stays current', async () => {
    await render();
    const link = container.querySelector<HTMLAnchorElement>(
      'a[href="https://docs.x.io"]',
    );

    expect(link?.textContent).toBe('docs.x.io');
    expect(link?.target).toBe('_blank');
    expect(container.textContent).toContain(
      'settings.sources.website.pagesByline',
    );
    expect(container.textContent).toContain('settings.sources.website.synced');
  });

  it('counts the sites of a source with several hosts', async () => {
    await render({
      hosts: ['docs.x.io', 'github.com'],
      syncFrequency: 'never',
    });

    expect(container.textContent).toContain(
      'settings.sources.website.sites {"count":2}',
    );
    expect(container.textContent).toContain(
      'settings.sources.website.notSynced',
    );
  });

  it('links an open page to its live address', async () => {
    await render({}, { 'upgrading.md': SITE['upgrading.md'] });
    // A one-page source opens the page directly.
    const link = container.querySelector<HTMLAnchorElement>(
      'a[href="https://docs.x.io/upgrading"]',
    );

    expect(link?.textContent).toBe('docs.x.io/upgrading');
    expect(container.textContent).toContain(
      'settings.sources.website.fetchedAt',
    );
  });
});
