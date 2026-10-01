import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { state } = vi.hoisted(() => ({
  state: {
    structure: {} as Record<string, unknown>,
    chunks: [] as Record<string, unknown>[],
  },
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

vi.mock('../../hooks', () => ({
  useDarkTheme: () => [false],
  useDebouncedValue: (value: unknown) => value,
  useLoaderState: (initial: boolean) => useState(initial),
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
  useOutsideAlerter: () => undefined,
}));

vi.mock('../../api/services/userService', () => ({
  default: {
    getDirectoryStructure: vi.fn(async () => ({
      json: async () => ({ directory_structure: state.structure }),
    })),
    getDocumentChunks: vi.fn(async () => ({
      ok: true,
      json: async () => ({
        page: 1,
        per_page: 12,
        total: state.chunks.length,
        chunks: state.chunks,
      }),
    })),
    updateChunk: vi.fn(async () => ({
      ok: true,
      json: async () => ({ chunk_id: 'c1' }),
    })),
  },
}));

import i18next from 'i18next';

import userService from '../../api/services/userService';
import TreeBrowser from './TreeBrowser';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const SOURCES = 'settings.sources.label';

const NESTED = {
  legal: {
    '2024': { 'msa.pdf': { type: 'pdf', size_bytes: 10, token_count: 700 } },
  },
  'readme.md': { type: 'md', size_bytes: 5, token_count: 300 },
};

describe('TreeBrowser', () => {
  let container: HTMLDivElement;
  let root: Root;
  let onBack: ReturnType<typeof vi.fn<() => void>>;

  const render = async (
    structure: Record<string, unknown>,
    props: Partial<React.ComponentProps<typeof TreeBrowser>> = {},
  ) => {
    state.structure = structure;
    await act(async () => {
      root.render(
        <TreeBrowser
          docId="doc"
          sourceName="Contracts"
          onBackToDocuments={onBack}
          columnOrder="size-first"
          topRightAction={<button type="button">Add file</button>}
          {...props}
        />,
      );
    });
  };

  beforeEach(() => {
    onBack = vi.fn<() => void>();
    state.chunks = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const rows = () =>
    Array.from(container.querySelectorAll('tbody tr')).map((tr) =>
      tr.querySelector('td')?.textContent?.trim(),
    );

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

  const navItem = (label: string) =>
    Array.from(
      container.querySelectorAll<HTMLElement>(
        'nav[aria-label="settings.sources.files"] [data-slot="command-item"]',
      ),
    ).find((el) => el.textContent?.includes(label));

  const tile = () =>
    container.querySelector<HTMLButtonElement>('button[data-slot="card"]');

  const chunkListOpen = () =>
    container.textContent?.includes('settings.sources.searchChunks') ?? false;

  it('returns to the root and to a parent folder from the crumbs', async () => {
    await render(NESTED);
    await openRow('legal');
    await openRow('2024');
    expect(crumbs()).toEqual([SOURCES, 'Contracts', 'legal', '2024']);

    await clickCrumb('legal');
    expect(crumbs()).toEqual([SOURCES, 'Contracts', 'legal']);

    await clickCrumb('Contracts');
    expect(crumbs()).toEqual([SOURCES, 'Contracts']);
  });

  it('one header: the open file is the last crumb and a folder crumb returns to it', async () => {
    await render(NESTED);
    await openRow('legal');
    await openRow('2024');
    await openRow('msa.pdf');
    expect(crumbs()).toEqual([
      SOURCES,
      'Contracts',
      'legal',
      '2024',
      'msa.pdf',
    ]);
    expect(container.querySelectorAll('[data-slot="breadcrumb"]')).toHaveLength(
      1,
    );
    expect(chunkListOpen()).toBe(true);

    await clickCrumb('legal');
    expect(crumbs()).toEqual([SOURCES, 'Contracts', 'legal']);
    expect(rows()).toContain('2024');
  });

  // Bugs row 8: the app language's separators, not the browser's.
  it('formats the byline and token cells in the app language', async () => {
    const language = i18next.language;
    i18next.language = 'de';
    try {
      await render({
        'big.pdf': { type: 'pdf', size_bytes: 10, token_count: 12345 },
        'small.md': { type: 'md', size_bytes: 5, token_count: 300 },
      });
      expect(container.textContent).toContain(
        'settings.sources.filesByline {"count":2,"files":"2","tokens":"12.645"}',
      );
      const cells = Array.from(container.querySelectorAll('td')).map(
        (td) => td.textContent,
      );
      expect(cells).toContain('12.345');
    } finally {
      i18next.language = language;
    }
  });

  it('shows the byline, badge and actions', async () => {
    await render(NESTED, { badge: <span>BADGE</span>, statusLabel: 'Busy' });
    expect(container.textContent).toContain(
      'settings.sources.filesByline {"count":2,"files":"2","tokens":"1,000"}',
    );
    expect(container.textContent).toContain('BADGE');
    expect(container.textContent).toContain('Busy');
    expect(container.textContent).toContain('Add file');
    expect(
      container.querySelector('[data-slot="command-input"]'),
    ).not.toBeNull();
    // The old header search is gone; the navigator's filter replaces it.
    expect(container.textContent).not.toContain('settings.sources.searchFiles');
  });

  it('titles the truncated folder and file names in the table', async () => {
    await render(NESTED);
    const titles = Array.from(
      container.querySelectorAll('tbody td span.truncate'),
    ).map((el) => el.getAttribute('title'));
    expect(titles).toEqual(['legal', 'readme.md']);
  });

  it('opens folders and files from the navigator', async () => {
    await render(NESTED);
    await act(async () => navItem('legal')!.click());
    expect(crumbs()).toEqual([SOURCES, 'Contracts', 'legal']);
    expect(rows()).toEqual(['2024']);
    expect(navItem('legal')!.dataset.checked).toBeDefined();

    await act(async () => navItem('readme.md')!.click());
    expect(crumbs()).toEqual([SOURCES, 'Contracts', 'readme.md']);
    expect(chunkListOpen()).toBe(true);
    expect(navItem('readme.md')!.getAttribute('data-checked')).not.toBeNull();
  });

  it('no back button or .. row: the Sources crumb leaves the source', async () => {
    await render(NESTED);
    await openRow('legal');
    expect(container.querySelector('.lucide-arrow-left')).toBeNull();
    expect(rows()).not.toContain('..');

    await clickCrumb('Contracts');
    expect(onBack).not.toHaveBeenCalled();
    await clickCrumb(SOURCES);
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('an open chunk is the last crumb, and the file crumb closes it', async () => {
    state.chunks = [{ doc_id: 'c1', text: '# Rates', metadata: {} }];
    await render(NESTED);
    await openRow('readme.md');
    await act(async () => tile()!.click());
    expect(crumbs()).toEqual([
      SOURCES,
      'Contracts',
      'readme.md',
      'settings.sources.chunkCrumb {"n":1}',
    ]);

    await clickCrumb('readme.md');
    expect(tile()).not.toBeNull();
    expect(crumbs()).toEqual([SOURCES, 'Contracts', 'readme.md']);
  });

  it('a saved chunk whose place is unknown keeps an unnumbered crumb', async () => {
    state.chunks = [{ doc_id: 'c1', text: '# Rates', metadata: {} }];
    await render(NESTED);
    await openRow('readme.md');
    await act(async () => tile()!.click());
    const button = (text: string) =>
      Array.from(document.body.querySelectorAll('button')).find(
        (el) => el.textContent?.trim() === text,
      )!;
    await act(async () => button('modals.chunk.edit').click());
    // After the save, the probed positions no longer hold the chunk.
    state.chunks = [];
    const field = document.body.querySelector<HTMLTextAreaElement>(
      '[role="dialog"] textarea',
    )!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        'value',
      )!.set!.call(field, '# Rates edited');
      field.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => button('modals.chunk.save').click());
    expect(crumbs()).toEqual([
      SOURCES,
      'Contracts',
      'readme.md',
      'settings.sources.chunkCrumbUnplaced',
    ]);

    await clickCrumb('readme.md');
    expect(crumbs()).toEqual([SOURCES, 'Contracts', 'readme.md']);
  });

  it('a one-file source opens straight on its chunk list', async () => {
    await render({ 'report.pdf': { type: 'pdf', display_name: 'Report' } });
    expect(
      container.querySelector('nav[aria-label="settings.sources.files"]'),
    ).toBeNull();
    expect(container.querySelector('table')).toBeNull();
    expect(chunkListOpen()).toBe(true);
    expect(crumbs()).toEqual([SOURCES, 'Contracts', 'Report']);
    expect(
      container.querySelectorAll('[data-slot="breadcrumb-link"]'),
    ).toHaveLength(1);

    await clickCrumb(SOURCES);
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('a one-file source inside a folder also opens straight on it', async () => {
    await render({ docs: { 'a.pdf': { type: 'pdf' } } });
    expect(
      container.querySelector('nav[aria-label="settings.sources.files"]'),
    ).toBeNull();
    expect(container.querySelector('table')).toBeNull();
    expect(chunkListOpen()).toBe(true);
    expect(crumbs()).toEqual([SOURCES, 'Contracts', 'a.pdf']);
  });

  it("a one-file source keeps the row menu's Delete in the header", async () => {
    const getRowMenuOptions = vi.fn(
      ({
        defaultViewOption,
        name,
      }: {
        defaultViewOption: unknown;
        name: string;
      }) => [defaultViewOption, { label: `delete ${name}`, onClick: vi.fn() }],
    );
    await render({ docs: { 'a.pdf': { type: 'pdf' } } }, {
      getRowMenuOptions,
    } as Partial<React.ComponentProps<typeof TreeBrowser>>);
    expect(getRowMenuOptions).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'docs/a.pdf', isFile: true }),
    );
    expect(
      container.querySelector('button[aria-label="settings.sources.menuAlt"]'),
    ).not.toBeNull();
  });

  it('canEdit false reaches the chunk list: no Add chunk', async () => {
    await render({ 'report.pdf': { type: 'pdf' } }, { canEdit: false });
    expect(chunkListOpen()).toBe(true);
    expect(container.textContent).not.toContain('settings.sources.addChunk');
  });

  it('an editable tree keeps Add chunk on the chunk list', async () => {
    await render({ 'report.pdf': { type: 'pdf' } });
    expect(container.textContent).toContain('settings.sources.addChunk');
  });

  it('a failed load says so and retries', async () => {
    const getDirectoryStructure = vi.mocked(userService.getDirectoryStructure);
    getDirectoryStructure.mockImplementationOnce(async () => {
      throw new Error('offline');
    });
    await render(NESTED);
    expect(container.textContent).toContain('settings.sources.filesLoadError');
    const retry = Array.from(container.querySelectorAll('button')).find(
      (el) => el.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(container.textContent).not.toContain(
      'settings.sources.filesLoadError',
    );
    expect(rows()).toEqual(['legal', 'readme.md']);
  });

  it('unmounting clears the crumbs it reported', async () => {
    const onCrumbsChange = vi.fn();
    await render(NESTED, { embedded: true, onCrumbsChange });
    expect(onCrumbsChange.mock.lastCall![0]).toHaveLength(1);
    await act(async () => root.unmount());
    expect(onCrumbsChange.mock.lastCall![0]).toEqual([]);
    root = createRoot(container);
  });

  it('a crumb step keeps focus in the header, on the new current crumb', async () => {
    await render(NESTED);
    await openRow('legal');
    await openRow('2024');
    const link = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-slot="breadcrumb-link"]',
      ),
    ).find((el) => el.textContent === 'legal')!;
    link.focus();
    await act(async () => link.click());
    const current = container.querySelector('[data-slot="breadcrumb-page"]')!;
    expect(current.textContent).toBe('legal');
    expect(document.activeElement).toBe(current);
  });

  it('embedded: no Sources crumb, badge or byline', async () => {
    await render(NESTED, { embedded: true, badge: <span>BADGE</span> });
    expect(crumbs()).toEqual(['Contracts']);
    expect(container.textContent).not.toContain('BADGE');
    expect(container.textContent).not.toContain('settings.sources.filesByline');
    expect(container.textContent).toContain('Add file');
  });

  it('embedded with an actions slot: no row of its own, actions in the slot', async () => {
    const slot = document.createElement('div');
    document.body.appendChild(slot);
    const onCrumbsChange = vi.fn();
    await render(NESTED, {
      embedded: true,
      actionsTarget: slot,
      onCrumbsChange,
    });
    expect(container.querySelector('[data-slot="breadcrumb"]')).toBeNull();
    expect(container.textContent).not.toContain('Add file');
    expect(slot.textContent).toContain('Add file');
    slot.remove();

    // The host draws the crumbs: the tree reports where it is.
    const labels = () =>
      (
        onCrumbsChange.mock.lastCall![0] as {
          label: string;
          onSelect?: () => void;
        }[]
      ).map((crumb) => crumb.label);
    expect(labels()).toEqual(['Contracts']);
    await openRow('legal');
    expect(labels()).toEqual(['Contracts', 'legal']);
    await act(async () => onCrumbsChange.mock.lastCall![0][0].onSelect());
    expect(labels()).toEqual(['Contracts']);
  });

  it('initialPath opens a nested file by its name, and again when it changes', async () => {
    await render(NESTED, { initialPath: 'msa.pdf' });
    expect(crumbs()).toEqual([
      SOURCES,
      'Contracts',
      'legal',
      '2024',
      'msa.pdf',
    ]);
    expect(chunkListOpen()).toBe(true);
    expect(navItem('msa.pdf')!.getAttribute('data-checked')).not.toBeNull();

    await render(NESTED, { initialPath: 'readme.md' });
    expect(crumbs()).toEqual([SOURCES, 'Contracts', 'readme.md']);
  });

  it('initialPath matches a full path or a display name', async () => {
    const structure = {
      docs: {
        'x_1.docx': { type: 'docx', display_name: 'Carrier profile.docx' },
      },
      'y.md': { type: 'md' },
    };
    await render(structure, { initialPath: 'Carrier profile.docx' });
    expect(crumbs()).toEqual([
      SOURCES,
      'Contracts',
      'docs',
      'Carrier profile.docx',
    ]);

    await render(structure, { initialPath: 'y.md' });
    expect(crumbs()).toEqual([SOURCES, 'Contracts', 'y.md']);
  });

  it('an initialPath not in the tree yet opens once a reload has it', async () => {
    const controllerRef: React.ComponentProps<
      typeof TreeBrowser
    >['controllerRef'] = { current: null };
    await render(NESTED, { initialPath: 'new.pdf', controllerRef });
    expect(chunkListOpen()).toBe(false);
    state.structure = { ...NESTED, 'new.pdf': { type: 'pdf' } };
    await act(async () => {
      await controllerRef.current!.refreshDirectory();
    });
    expect(crumbs()).toEqual([SOURCES, 'Contracts', 'new.pdf']);
  });

  it('an unknown initialPath leaves the root open', async () => {
    await render(NESTED, { initialPath: 'missing.pdf' });
    expect(crumbs()).toEqual([SOURCES, 'Contracts']);
    expect(chunkListOpen()).toBe(false);
  });

  // Numbers read down a column: size and tokens are right-aligned with
  // tabular figures in either column order, headers included.
  it.each(['size-first', 'tokens-first'] as const)(
    'right-aligns the numeric columns (%s)',
    async (columnOrder) => {
      await render(NESTED, { columnOrder });
      const headers = Array.from(container.querySelectorAll('thead th'));
      [1, 2].forEach((index) =>
        expect(headers[index].className).toContain('text-right'),
      );
      const row = Array.from(container.querySelectorAll('tbody tr')).find(
        (tr) => tr.querySelector('td')?.textContent?.trim() === 'readme.md',
      )!;
      const cells = Array.from(row.querySelectorAll('td'));
      [1, 2].forEach((index) => {
        expect(cells[index].className).toContain('text-right');
        expect(cells[index].className).toContain('tabular-nums');
      });
    },
  );
});
