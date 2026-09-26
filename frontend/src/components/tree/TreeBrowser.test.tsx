import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => null,
}));

vi.mock('../../hooks', () => ({
  useDarkTheme: () => [false],
  useDebouncedValue: (value: unknown) => value,
  useLoaderState: (initial: boolean) => useState(initial),
  useMediaQuery: () => ({ isMobile: false }),
  useOutsideAlerter: () => undefined,
}));

vi.mock('../../api/services/userService', () => ({
  default: {
    getDirectoryStructure: vi.fn(async () => ({
      json: async () => ({
        directory_structure: {
          legal: { '2024': { 'msa.pdf': { type: 'pdf', size_bytes: 10 } } },
        },
      }),
    })),
    getDocumentChunks: vi.fn(async () => ({
      ok: true,
      json: async () => ({ page: 1, per_page: 5, total: 0, chunks: [] }),
    })),
  },
}));

import TreeBrowser from './TreeBrowser';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('TreeBrowser path crumbs', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(
        <TreeBrowser
          docId="doc"
          sourceName="Contracts"
          onBackToDocuments={vi.fn()}
          columnOrder="size-first"
          topRightAction={null}
        />,
      );
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const openRow = async (name: string) => {
    const row = Array.from(container.querySelectorAll('tr')).find(
      (tr) => tr.querySelector('td')?.textContent?.trim() === name,
    );
    if (!row) throw new Error(`no row ${name}`);
    await act(async () => row.click());
  };

  const crumbs = () =>
    Array.from(container.querySelectorAll('[data-slot="breadcrumb-item"]')).map(
      (el) => el.textContent,
    );

  const clickCrumb = async (label: string) => {
    const link = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-slot="breadcrumb-link"]',
      ),
    ).find((el) => el.textContent === label);
    if (!link) throw new Error(`no crumb link ${label}`);
    await act(async () => link.click());
  };

  it('returns to the root and to a parent folder from the crumbs', async () => {
    await openRow('legal');
    await openRow('2024');
    expect(crumbs()).toEqual(['Contracts', 'legal', '2024']);

    await clickCrumb('legal');
    expect(crumbs()).toEqual(['Contracts', 'legal']);

    await clickCrumb('Contracts');
    expect(crumbs()).toEqual(['Contracts']);
  });

  it('a folder crumb in the chunk viewer returns to that folder', async () => {
    await openRow('legal');
    await openRow('2024');
    await openRow('msa.pdf');
    expect(crumbs()).toEqual(['Contracts', 'legal', '2024', 'msa.pdf']);

    await clickCrumb('legal');
    expect(crumbs()).toEqual(['Contracts', 'legal']);
    expect(container.textContent).toContain('2024');
  });
});
