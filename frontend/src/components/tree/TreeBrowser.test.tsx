import { act, StrictMode, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { TreeBrowserController } from './types';

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

  it('shows a refreshed structure under StrictMode', async () => {
    // StrictMode mounts, unmounts and mounts again; a mounted flag that only
    // ever turns false dropped every refresh after a delete or an add.
    const controllerRef = {
      current: null,
    } as React.MutableRefObject<TreeBrowserController | null>;
    state.structure = NESTED;
    await act(async () => {
      root.render(
        <StrictMode>
          <TreeBrowser
            docId="doc"
            sourceName="Contracts"
            onBackToDocuments={onBack}
            columnOrder="size-first"
            topRightAction={null}
            controllerRef={controllerRef}
          />
        </StrictMode>,
      );
    });
    expect(rows()).toEqual(['legal', 'readme.md']);

    state.structure = {
      legal: NESTED.legal,
      'notes.md': { type: 'md', size_bytes: 5, token_count: 10 },
    };
    let refreshed = false;
    await act(async () => {
      refreshed = (await controllerRef.current?.refreshDirectory()) ?? false;
    });

    expect(refreshed).toBe(true);
    expect(rows()).toEqual(['legal', 'notes.md']);
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

  // The title row holds source-level actions only: a one-file source's
  // file actions are not moved into it.
  it("a one-file source keeps its file's menu out of the title row", async () => {
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
    // The file's own menu is in its bar, not the title row.
    const menus = Array.from(
      container.querySelectorAll(
        'button[aria-label="settings.sources.menuAlt"]',
      ),
    );
    expect(menus).toHaveLength(1);
    expect(menus[0].closest('[data-testid="item-bar"]')).not.toBeNull();
  });

  it("draws the source's menu last in the title row", async () => {
    await render({ 'a.pdf': { type: 'pdf' }, 'b.pdf': { type: 'pdf' } }, {
      topRightAction: <button type="button">primary</button>,
      headerMenu: <button type="button">source menu</button>,
    } as Partial<React.ComponentProps<typeof TreeBrowser>>);
    const menu = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'source menu',
    )!;
    expect(menu.previousElementSibling?.textContent).toBe('primary');
    expect(menu.nextElementSibling).toBeNull();
  });

  const itemBar = () =>
    container.querySelector<HTMLElement>('[data-testid="item-bar"]');
  const openItemMenu = async () => {
    const trigger = itemBar()!.querySelector<HTMLButtonElement>(
      'button[aria-label="settings.sources.menuAlt"]',
    )!;
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
    return Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).map((el) => el.textContent);
  };
  const rowMenu = vi.fn(
    ({
      defaultViewOption,
      name,
    }: {
      defaultViewOption: { label: string };
      name: string;
    }) => [
      defaultViewOption,
      { label: `open ${name}`, onClick: vi.fn() },
      {
        label: `delete ${name}`,
        onClick: vi.fn(),
        variant: 'destructive' as const,
      },
    ],
  );

  it('an open file gets a bar above its chunks: name, size, counts, its menu less View', async () => {
    state.chunks = [{ doc_id: 'c1', text: 'a', metadata: {} }];
    await render(NESTED, {
      getRowMenuOptions: rowMenu,
    } as Partial<React.ComponentProps<typeof TreeBrowser>>);
    await openRow('readme.md');
    const bar = itemBar()!;
    expect(bar).not.toBeNull();
    expect(bar.textContent).toContain('readme.md');
    expect(bar.textContent).toContain('5 Bytes');
    expect(bar.textContent).toContain('settings.sources.chunkCount');
    expect(bar.textContent).toContain('settings.sources.item.tokens');
    // The bar sits above the chunk list.
    const search = Array.from(container.querySelectorAll('input')).pop()!;
    expect(
      bar.compareDocumentPosition(search) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(await openItemMenu()).toEqual([
      'open readme.md',
      'delete readme.md',
    ]);
    state.chunks = [];
  });

  it('a file opened from the navigator gets the same bar', async () => {
    await render(NESTED, {
      getRowMenuOptions: rowMenu,
    } as Partial<React.ComponentProps<typeof TreeBrowser>>);
    await act(async () => navItem('legal')!.click());
    await act(async () => navItem('2024')!.click());
    await act(async () => navItem('msa.pdf')!.click());
    expect(itemBar()?.textContent).toContain('msa.pdf');
    // The row menu gets the name inside its folder, as the table row does.
    expect(rowMenu).toHaveBeenLastCalledWith(
      expect.objectContaining({ name: 'msa.pdf', isFile: true }),
    );
  });

  it('the last item has no Delete; with nothing else, no menu at all', async () => {
    const deleteOnly = vi.fn(
      ({ defaultViewOption }: { defaultViewOption: unknown }) => [
        defaultViewOption,
        { label: 'delete', onClick: vi.fn(), variant: 'destructive' as const },
      ],
    );
    await render({ 'a.pdf': { type: 'pdf', size_bytes: 2048 } }, {
      getRowMenuOptions: deleteOnly,
    } as Partial<React.ComponentProps<typeof TreeBrowser>>);
    expect(itemBar()?.textContent).toContain('a.pdf');
    expect(
      itemBar()!.querySelector('button[aria-label="settings.sources.menuAlt"]'),
    ).toBeNull();

    await render({ 'a.pdf': { type: 'pdf' } }, {
      getRowMenuOptions: rowMenu,
    } as Partial<React.ComponentProps<typeof TreeBrowser>>);
    expect(await openItemMenu()).toEqual(['open a.pdf']);
  });

  it('a page bar links its address and says when it was fetched', async () => {
    await render(
      {
        'air.md': {
          type: 'md',
          token_count: 40,
          url: 'https://docs.x.io/Deploying/Air',
          display_name: 'Air-Gapped Deployment',
          fetched_at: new Date().toISOString(),
        },
      },
      { variant: 'pages' } as Partial<React.ComponentProps<typeof TreeBrowser>>,
    );
    const bar = itemBar()!;
    expect(bar.textContent).toContain('Air-Gapped Deployment');
    const link = bar.querySelector('a')!;
    expect(link.getAttribute('href')).toBe('https://docs.x.io/Deploying/Air');
    expect(link.textContent).toContain('docs.x.io/Deploying/Air');
    expect(bar.textContent).toContain('settings.sources.website.fetchedAt');
  });

  it("the byline stays the source's while a file is open", async () => {
    const renderByline = vi.fn(() => 'source byline');
    await render(NESTED, {
      renderByline,
    } as Partial<React.ComponentProps<typeof TreeBrowser>>);
    await openRow('readme.md');
    expect(container.textContent).toContain('source byline');
    for (const [context] of renderByline.mock.calls as unknown as [
      Record<string, unknown>,
    ][])
      expect(context).not.toHaveProperty('openFile');
  });

  it('puts the notice under the bar, above the chunks', async () => {
    await render({ 'a.pdf': { type: 'pdf' } }, {
      chunksNotice: <p data-testid="notice">hand edits</p>,
    } as Partial<React.ComponentProps<typeof TreeBrowser>>);
    const notice = container.querySelector('[data-testid="notice"]')!;
    expect(notice.previousElementSibling).toBe(itemBar());
  });

  it('closes a file that a refresh no longer lists', async () => {
    const controllerRef: { current: TreeBrowserController | null } = {
      current: null,
    };
    await render(NESTED, { controllerRef } as Partial<
      React.ComponentProps<typeof TreeBrowser>
    >);
    await openRow('readme.md');
    expect(itemBar()).not.toBeNull();
    state.structure = { legal: NESTED.legal, 'other.md': { type: 'md' } };
    await act(async () => {
      await controllerRef.current?.refreshDirectory();
    });
    expect(itemBar()).toBeNull();
    expect(container.querySelector('table')).not.toBeNull();
  });

  it('reloadFile lists the open file again and closes its open chunk', async () => {
    const controllerRef: { current: TreeBrowserController | null } = {
      current: null,
    };
    state.chunks = [{ doc_id: 'c1', text: '# Rates', metadata: {} }];
    await render(NESTED, { controllerRef } as Partial<
      React.ComponentProps<typeof TreeBrowser>
    >);
    await openRow('readme.md');
    await act(async () => tile()!.click());
    const listed = () =>
      vi
        .mocked(userService.getDocumentChunks)
        .mock.calls.filter((call) => call[4] === 'readme.md').length;
    const before = listed();

    // Another file isn't the open one: nothing to reload.
    await act(async () => controllerRef.current?.reloadFile('legal/x.md'));
    expect(listed()).toBe(before);

    state.chunks = [{ doc_id: 'c2', text: '# New rates', metadata: {} }];
    await act(async () => controllerRef.current?.reloadFile('readme.md'));
    expect(listed()).toBe(before + 1);
    expect(crumbs()).toEqual([SOURCES, 'Contracts', 'readme.md']);
    expect(tile()?.textContent).toContain('New rates');
  });

  it('a page bar links only a web address', async () => {
    await render(
      {
        'air.md': {
          type: 'md',
          token_count: 40,
          url: 'javascript:alert(1)',
          display_name: 'Air',
        },
      },
      { variant: 'pages' } as Partial<React.ComponentProps<typeof TreeBrowser>>,
    );
    expect(itemBar()!.querySelector('a')).toBeNull();
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

  it('a linked chunk opens in its file, and only the first time', async () => {
    state.chunks = [
      { doc_id: 'c1', text: 'Scope', metadata: {} },
      { doc_id: 'c2', text: 'Liability cap', metadata: {} },
    ];
    await render(NESTED, {
      initialPath: 'msa.pdf',
      linkedChunk: { id: 'c2', search: 'Liability', path: 'msa.pdf' },
    });
    // The file's chunk list searched for it, with that chunk open.
    const calls = vi.mocked(userService.getDocumentChunks).mock.calls;
    expect(calls.at(-1)?.[4]).toBe('legal/2024/msa.pdf');
    expect(calls.at(-1)?.[5]).toBe('Liability');
    expect(crumbs().at(-1)).toContain('settings.sources.chunkCrumb');
    expect(container.textContent).toContain('Liability cap');

    // Leaving the file drops the link: opening it again lists its chunks.
    await clickCrumb('Contracts');
    await openRow('legal');
    await openRow('2024');
    await openRow('msa.pdf');
    expect(chunkListOpen()).toBe(true);
    expect(
      vi.mocked(userService.getDocumentChunks).mock.calls.at(-1)?.[5],
    ).toBe('');
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
