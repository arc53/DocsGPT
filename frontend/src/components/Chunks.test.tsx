import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { dispatch, service, pagerProps } = vi.hoisted(() => ({
  pagerProps: {
    current: null as null | { onPageSizeChange?: (size: number) => void },
  },
  dispatch: vi.fn(),
  service: {
    getDocumentChunks: vi.fn(),
    addChunk: vi.fn(),
    updateChunk: vi.fn(),
    deleteChunk: vi.fn(),
  },
}));

// Keys come back as-is; interpolation values are appended so the tests can
// read them ("key {"n":1}").
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key} ${JSON.stringify(opts)}` : key,
  }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => null,
  useDispatch: () => dispatch,
}));

vi.mock('../hooks', () => ({
  useDarkTheme: () => [false],
  useDebouncedValue: (value: unknown) => value,
  useLoaderState: (initial: boolean) => useState(initial),
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
  useOutsideAlerter: () => undefined,
}));

vi.mock('../api/services/userService', () => ({ default: service }));

// The real pager, with its props kept so a test can pick a page size without
// driving the Select popover.
vi.mock('./ui/pagination', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./ui/pagination')>();
  return {
    ...mod,
    Pagination: (props: React.ComponentProps<typeof mod.Pagination>) => {
      pagerProps.current = props;
      return mod.Pagination(props);
    },
  };
});

import Chunks from './Chunks';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const chunksResponse = (overrides: Record<string, unknown> = {}) => ({
  ok: true,
  json: async () => ({
    page: 1,
    per_page: 12,
    total: 1,
    chunks: [
      {
        doc_id: 'c1',
        text: '## Late pickup clause',
        metadata: { token_count: 42 },
      },
    ],
    ...overrides,
  }),
});

const setFieldValue = (
  field: HTMLInputElement | HTMLTextAreaElement,
  value: string,
) => {
  const proto =
    field instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(field, value);
  field.dispatchEvent(new Event('input', { bubbles: true }));
};

describe('Chunks', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    dispatch.mockReset();
    service.getDocumentChunks.mockReset();
    service.getDocumentChunks.mockImplementation(async () => chunksResponse());
    service.addChunk.mockReset();
    service.updateChunk.mockReset();
    service.deleteChunk.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (
    props: Partial<React.ComponentProps<typeof Chunks>> = {},
  ) => {
    await act(async () => {
      root.render(
        <Chunks
          documentId="doc"
          documentName="Contracts"
          handleGoBack={vi.fn()}
          {...props}
        />,
      );
    });
  };

  const tile = () =>
    container.querySelector<HTMLButtonElement>('button[data-slot="card"]');

  const buttonByText = (text: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((el) => el.textContent?.trim() === text);

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

  const buttonByLabel = (label: string) =>
    document.body.querySelector<HTMLButtonElement>(
      `button[aria-label="${label}"]`,
    );

  it('has no file search column', async () => {
    await render();
    expect(container.querySelector('[data-slot="command-input"]')).toBeNull();
    expect(container.innerHTML).not.toContain('198px');
  });

  it('draws each chunk as a filled tile with a cleaned preview and #n · tokens footer', async () => {
    await render();
    const card = tile()!;
    expect(card.dataset.variant).toBe('filled');
    expect(card.dataset.padding).toBe('lg');
    expect(card.querySelector('p')!.textContent).toBe('Late pickup clause');
    const footer = card.querySelector('[data-slot="card-footer"]')!;
    expect(footer.textContent).toBe(
      'settings.sources.chunkTileMeta {"n":1,"tokens":"42"}',
    );
    // No muted strip on the muted tile: it would disappear.
    expect(card.querySelector('.bg-muted')).toBeNull();
  });

  it('numbers tiles from the page offset', async () => {
    service.getDocumentChunks.mockImplementation(async () =>
      chunksResponse({
        page: 2,
        total: 30,
        chunks: [
          { doc_id: 'a', text: 'A', metadata: {} },
          { doc_id: 'b', text: 'B', metadata: {} },
        ],
      }),
    );
    await render();
    const footers = Array.from(
      container.querySelectorAll('[data-slot="card-footer"]'),
    ).map((el) => el.textContent);
    expect(footers[0]).toContain('"n":13');
    expect(footers[1]).toContain('"n":14');
  });

  // Decision 79: text tiles follow the container with an auto-fit track that
  // can't overflow a container narrower than 400px.
  it('lays the tiles out on the guarded auto-fit text-tile grid', async () => {
    await render();
    expect(tile()!.parentElement!.className).toBe(
      'grid grid-cols-1 gap-4 sm:grid-cols-[repeat(auto-fit,minmax(min(400px,100%),1fr))]',
    );
  });

  it('shows the search field, the muted count and Add chunk', async () => {
    await render({ embedded: true });
    expect(container.textContent).toContain('settings.sources.searchChunks');
    expect(container.textContent).toContain(
      'settings.sources.chunkCount {"count":1,"formatted":"1"}',
    );
    expect(buttonByText('settings.sources.addChunk')).toBeDefined();
  });

  // The header's byline already carries it; only a chunk list inside a file
  // tree (whose byline is the tree's totals) repeats the count in the toolbar.
  it('standalone: the chunk count shows once, in the byline', async () => {
    await render();
    const count = 'settings.sources.chunkCount {"count":1,"formatted":"1"}';
    expect(container.textContent!.split(count)).toHaveLength(2);
    expect(
      container.querySelector('p.text-sm.text-muted-foreground')?.textContent,
    ).toBe(count);
  });

  it('asks for 12 chunks per page and labels the page-size select', async () => {
    service.getDocumentChunks.mockImplementation(async () =>
      chunksResponse({ total: 30 }),
    );
    await render();
    expect(service.getDocumentChunks.mock.calls[0][2]).toBe(12);
    const pager = container.querySelector('[data-slot="pagination"]')!;
    expect(pager.textContent).toContain('pagination.chunksPerPage');
  });

  // Bugs row 1: at 48 per page a 30-chunk source still keeps its pager, so a
  // smaller page size can be picked again.
  it('keeps the pager when the page size outgrows the chunk count', async () => {
    service.getDocumentChunks.mockImplementation(
      async (_id: string, _page: number, perPage: number) =>
        chunksResponse({ total: 30, per_page: perPage }),
    );
    await render();
    await act(async () => pagerProps.current!.onPageSizeChange!(48));
    expect(service.getDocumentChunks.mock.lastCall![2]).toBe(48);
    const pager = container.querySelector('[data-slot="pagination"]');
    expect(pager).not.toBeNull();
    expect(pager!.textContent).toContain('pagination.chunksPerPage');
  });

  it('draws no pager for 12 chunks or fewer', async () => {
    service.getDocumentChunks.mockImplementation(async () =>
      chunksResponse({ total: 12 }),
    );
    await render();
    expect(container.querySelector('[data-slot="pagination"]')).toBeNull();
  });

  it('standalone: Sources › the source, and the Sources crumb leaves it', async () => {
    const handleGoBack = vi.fn();
    await render({ handleGoBack, headerAction: <span>retrieval</span> });
    expect(crumbs()).toEqual(['settings.sources.label', 'Contracts']);
    expect(container.textContent).toContain('retrieval');
    await clickCrumb('settings.sources.label');
    expect(handleGoBack).toHaveBeenCalledTimes(1);
  });

  it('embedded: draws no header', async () => {
    await render({ embedded: true });
    expect(container.querySelector('[data-slot="breadcrumb-item"]')).toBeNull();
  });

  const drawer = () => document.body.querySelector('[role="dialog"]');

  // Chunk n of a 3-chunk list served one per page.
  const THREE = ['# First', '# Second', '# Third'];
  const serveThree = () =>
    service.getDocumentChunks.mockImplementation(
      async (_id: string, page: number, perPage: number) =>
        perPage === 1
          ? chunksResponse({
              page,
              per_page: 1,
              total: 3,
              chunks: [
                {
                  doc_id: `c${page}`,
                  text: THREE[page - 1],
                  metadata: { token_count: page },
                },
              ],
            })
          : chunksResponse({
              total: 3,
              chunks: THREE.map((text, i) => ({
                doc_id: `c${i + 1}`,
                text,
                metadata: { token_count: i + 1 },
              })),
            }),
    );

  it('opens a chunk rendered in the reader panel and returns to the list', async () => {
    const controllerRef: React.ComponentProps<typeof Chunks>['controllerRef'] =
      { current: null };
    const onOpenChunkChange = vi.fn();
    await render({ embedded: true, controllerRef, onOpenChunkChange });
    await act(async () => tile()!.click());
    expect(tile()).toBeNull();
    expect(container.textContent).toContain(
      'settings.sources.chunkPosition {"n":1,"total":1,"tokens":"42"}',
    );
    // Markdown reads rendered: no textarea, the heading is a heading.
    expect(container.querySelector('textarea')).toBeNull();
    expect(container.querySelector('h2')?.textContent).toBe(
      'Late pickup clause',
    );
    // The host's crumbs close it; the reader has no Back of its own.
    expect(onOpenChunkChange).toHaveBeenLastCalledWith(1);
    expect(container.querySelector('.lucide-arrow-left')).toBeNull();

    await act(async () => controllerRef.current!.closeChunk());
    expect(tile()).not.toBeNull();
    expect(onOpenChunkChange).toHaveBeenLastCalledWith(null);
  });

  it('renders a markdown heading as an h1', async () => {
    service.getDocumentChunks.mockImplementation(async () =>
      chunksResponse({
        chunks: [{ doc_id: 'c1', text: '# Rates\n\nBody', metadata: {} }],
      }),
    );
    await render({ embedded: true });
    await act(async () => tile()!.click());
    expect(container.querySelector('h1')?.textContent).toBe('Rates');
  });

  it('standalone: an open chunk is the last crumb and the source crumb closes it', async () => {
    const handleGoBack = vi.fn();
    await render({ handleGoBack });
    await act(async () => tile()!.click());
    expect(crumbs()).toEqual([
      'settings.sources.label',
      'Contracts',
      'settings.sources.chunkCrumb {"n":1}',
    ]);
    await clickCrumb('Contracts');
    expect(handleGoBack).not.toHaveBeenCalled();
    expect(tile()).not.toBeNull();
    expect(crumbs()).toEqual(['settings.sources.label', 'Contracts']);
  });

  it('previous / next fetch chunk n one per page and stop at the ends', async () => {
    serveThree();
    await render({ embedded: true, path: 'a/b.md' });
    await act(async () => tile()!.click());
    const prev = () => buttonByLabel('settings.sources.previousChunk')!;
    const next = () => buttonByLabel('settings.sources.nextChunk')!;
    expect(prev().disabled).toBe(true);
    expect(next().disabled).toBe(false);

    service.getDocumentChunks.mockClear();
    await act(async () => next().click());
    expect(service.getDocumentChunks).toHaveBeenCalledWith(
      'doc',
      2,
      1,
      null,
      'a/b.md',
      '',
    );
    expect(container.querySelector('h1')?.textContent).toBe('Second');
    expect(container.textContent).toContain(
      'settings.sources.chunkPosition {"n":2,"total":3,"tokens":"2"}',
    );

    await act(async () => next().click());
    expect(container.querySelector('h1')?.textContent).toBe('Third');
    expect(next().disabled).toBe(true);
    expect(prev().disabled).toBe(false);

    await act(async () => prev().click());
    expect(service.getDocumentChunks).toHaveBeenLastCalledWith(
      'doc',
      2,
      1,
      null,
      'a/b.md',
      '',
    );
    expect(container.querySelector('h1')?.textContent).toBe('Second');
  });

  it('the arrow keys walk the chunks while no field has focus', async () => {
    serveThree();
    await render({ embedded: true });
    await act(async () => tile()!.click());
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
    });
    expect(container.querySelector('h1')?.textContent).toBe('Second');
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));
    });
    expect(container.querySelector('h1')?.textContent).toBe('First');
  });

  // 13 chunks, 12 per page: chunk 13 sits on page 2.
  const serveThirteen = () =>
    service.getDocumentChunks.mockImplementation(
      async (_id: string, page: number, perPage: number) =>
        perPage === 1
          ? chunksResponse({
              page,
              per_page: 1,
              total: 13,
              chunks: [
                { doc_id: `c${page}`, text: `# C${page}`, metadata: {} },
              ],
            })
          : chunksResponse({
              page,
              total: 13,
              chunks: Array.from({ length: page === 2 ? 1 : 12 }, (_, i) => ({
                doc_id: `p${page}-${i}`,
                text: `tile ${page}-${i}`,
                metadata: {},
              })),
            }),
    );

  it('back to the grid lands on the page holding the last chunk', async () => {
    const controllerRef: React.ComponentProps<typeof Chunks>['controllerRef'] =
      { current: null };
    serveThirteen();
    await render({ embedded: true, controllerRef });
    const tiles = container.querySelectorAll<HTMLButtonElement>(
      'button[data-slot="card"]',
    );
    await act(async () => tiles[11].click());
    await act(async () => buttonByLabel('settings.sources.nextChunk')!.click());
    expect(container.querySelector('h1')?.textContent).toBe('C13');
    await act(async () => controllerRef.current!.closeChunk());
    const lastGridCall = service.getDocumentChunks.mock.calls
      .filter((call) => call[2] !== 1)
      .pop()!;
    expect(lastGridCall[1]).toBe(2);
    expect(tile()!.textContent).toContain('tile 2-0');
  });

  it('Edit opens the drawer with the chunk text and saves it', async () => {
    service.getDocumentChunks.mockImplementation(async () =>
      chunksResponse({
        chunks: [
          {
            doc_id: 'c1',
            text: '## Late pickup clause',
            metadata: { token_count: 42, title: 'Clause' },
          },
        ],
      }),
    );
    service.updateChunk.mockImplementation(async () => ({
      ok: true,
      json: async () => ({ chunk_id: 'c1-new' }),
    }));
    await render({ embedded: true, path: 'legal/msa.pdf' });
    await act(async () => tile()!.click());
    // No in-panel edit mode any more.
    expect(buttonByText('modals.chunk.cancel')).toBeUndefined();
    await act(async () => buttonByText('modals.chunk.edit')!.click());
    expect(drawer()).not.toBeNull();
    expect(drawer()!.textContent).toContain('settings.sources.editChunk');
    expect(drawer()!.textContent).toContain(
      'settings.sources.editChunkDescription {"file":"legal/msa.pdf","n":1,"tokens":"42"',
    );
    const field = drawer()!.querySelector('textarea')!;
    expect(field.value).toBe('## Late pickup clause');

    await act(async () => setFieldValue(field, '## New text'));
    service.getDocumentChunks.mockClear();
    await act(async () => buttonByText('modals.chunk.save')!.click());
    expect(service.updateChunk).toHaveBeenCalledWith(
      {
        id: 'doc',
        chunk_id: 'c1',
        text: '## New text',
        metadata: { title: 'Clause' },
      },
      null,
    );
    expect(drawer()).toBeNull();
    // That chunk and the grid page are fetched again.
    const sizes = service.getDocumentChunks.mock.calls.map((call) => call[2]);
    expect(sizes).toContain(1);
    expect(sizes).toContain(12);
  });

  it('an edit the search no longer matches still shows the saved text', async () => {
    service.updateChunk.mockImplementation(async () => ({
      ok: true,
      json: async () => ({ chunk_id: 'c1-new' }),
    }));
    const onOpenChunkChange = vi.fn();
    await render({ embedded: true, onOpenChunkChange });
    await act(async () => tile()!.click());
    await act(async () => buttonByText('modals.chunk.edit')!.click());
    // After the save, the open position holds nothing (or another chunk).
    service.getDocumentChunks.mockImplementation(async () =>
      chunksResponse({ total: 0, chunks: [] }),
    );
    const field = drawer()!.querySelector('textarea')!;
    await act(async () => setFieldValue(field, '## Rewritten'));
    await act(async () => buttonByText('modals.chunk.save')!.click());
    expect(drawer()).toBeNull();
    expect(container.querySelector('h2')?.textContent).toBe('Rewritten');
    expect(container.textContent).toContain('chunkPositionUnplaced');
    expect(buttonByLabel('settings.sources.nextChunk')!.disabled).toBe(true);
    // An embedding host draws the crumb: still open, but with no number.
    expect(onOpenChunkChange).toHaveBeenLastCalledWith('unplaced');
  });

  it('deleting the only chunk on the last page lands on the page before', async () => {
    const controllerRef: React.ComponentProps<typeof Chunks>['controllerRef'] =
      { current: null };
    serveThirteen();
    service.deleteChunk.mockImplementation(async () => ({ ok: true }));
    await render({ embedded: true, controllerRef });
    const tiles = container.querySelectorAll<HTMLButtonElement>(
      'button[data-slot="card"]',
    );
    await act(async () => tiles[11].click());
    await act(async () => buttonByLabel('settings.sources.nextChunk')!.click());
    expect(container.querySelector('h1')?.textContent).toBe('C13');

    const trigger = buttonByLabel('settings.sources.menuAlt')!;
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
    const del = Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((el) => el.textContent === 'modals.chunk.delete')!;
    await act(async () => del.click());
    await act(async () => buttonByText('modals.chunk.delete')!.click());

    expect(service.deleteChunk).toHaveBeenCalledWith('doc', 'c13', null);
    const lastGridCall = service.getDocumentChunks.mock.calls
      .filter((call) => call[2] !== 1)
      .pop()!;
    expect(lastGridCall[1]).toBe(1);
  });

  it('drops a grid response that a newer fetch overtook', async () => {
    const controllerRef: React.ComponentProps<typeof Chunks>['controllerRef'] =
      { current: null };
    serveThirteen();
    await render({ embedded: true, controllerRef });
    // Open chunk 13 (page 2), then start a slow page-1 refresh and close the
    // chunk before it answers.
    const tiles = container.querySelectorAll<HTMLButtonElement>(
      'button[data-slot="card"]',
    );
    await act(async () => tiles[11].click());
    await act(async () => buttonByLabel('settings.sources.nextChunk')!.click());
    let release: () => void = () => undefined;
    const slow = new Promise<void>((resolve) => {
      release = resolve;
    });
    const fast = service.getDocumentChunks.getMockImplementation()! as (
      ...a: unknown[]
    ) => unknown;
    // Grid page 1 answers only once released.
    service.getDocumentChunks.mockImplementation(async (...args: unknown[]) => {
      if (args[1] === 1 && args[2] !== 1) await slow;
      return fast(...args);
    });
    service.updateChunk.mockImplementation(async () => ({
      ok: true,
      json: async () => ({ chunk_id: 'c13' }),
    }));
    await act(async () => buttonByText('modals.chunk.edit')!.click());
    const field = drawer()!.querySelector('textarea')!;
    await act(async () => setFieldValue(field, '# C13 edited'));
    await act(async () => buttonByText('modals.chunk.save')!.click());
    await act(async () => controllerRef.current!.closeChunk());
    expect(tile()!.textContent).toContain('tile 2-0');
    await act(async () => release());
    expect(tile()!.textContent).toContain('tile 2-0');
  });

  it('a failed save keeps the drawer open with a destructive alert', async () => {
    service.updateChunk.mockImplementation(async () => ({ ok: false }));
    await render({ embedded: true });
    await act(async () => tile()!.click());
    await act(async () => buttonByText('modals.chunk.edit')!.click());
    const field = drawer()!.querySelector('textarea')!;
    await act(async () => setFieldValue(field, 'New text'));
    await act(async () => buttonByText('modals.chunk.save')!.click());
    expect(service.updateChunk).toHaveBeenCalledTimes(1);
    expect(drawer()).not.toBeNull();
    const alert = drawer()!.querySelector('[data-slot="alert"]')!;
    expect(alert.getAttribute('data-variant')).toBe('destructive');
    expect(alert.textContent).toBe('settings.sources.chunkErrors.save');
    expect(dispatch).not.toHaveBeenCalled();
    // The edits stay in the drawer.
    expect(drawer()!.querySelector('textarea')!.value).toBe('New text');
  });

  it('Add chunk opens the drawer empty, adds and stays on the grid', async () => {
    service.addChunk.mockImplementation(async () => ({ ok: true }));
    await render({ embedded: true, path: 'a.md' });
    await act(async () => buttonByText('settings.sources.addChunk')!.click());
    expect(
      drawer()!.querySelector('h2, [data-slot="sheet-title"]')!.textContent,
    ).toBe('settings.sources.addChunk');
    const field = drawer()!.querySelector('textarea')!;
    expect(field.value).toBe('');
    // The title defaults to the file's name, as ingest sets it.
    expect(drawer()!.querySelector('input')!.value).toBe('a.md');
    await act(async () => setFieldValue(field, 'Fresh'));
    service.getDocumentChunks.mockClear();
    await act(async () => buttonByText('modals.chunk.add')!.click());
    expect(service.addChunk).toHaveBeenCalledWith(
      {
        id: 'doc',
        text: 'Fresh',
        metadata: { source: 'a.md', source_id: 'doc', title: 'a.md' },
      },
      null,
    );
    expect(drawer()).toBeNull();
    expect(service.getDocumentChunks).toHaveBeenCalledTimes(1);
    expect(tile()).not.toBeNull();
  });

  it("Add chunk's title follows the file's other chunks, then its display name", async () => {
    service.getDocumentChunks.mockImplementation(async () =>
      chunksResponse({
        chunks: [
          { doc_id: 'c1', text: 'x', metadata: { title: 'Carrier profile' } },
        ],
      }),
    );
    await render({
      embedded: true,
      path: 'x_1.docx',
      fileName: 'Carrier.docx',
    });
    await act(async () => buttonByText('settings.sources.addChunk')!.click());
    expect(drawer()!.querySelector('input')!.value).toBe('Carrier profile');
    await act(async () =>
      buttonByText('settings.sources.editor.cancel')!.click(),
    );

    service.getDocumentChunks.mockImplementation(async () => chunksResponse());
    await render({ embedded: true, path: 'x_2.docx', fileName: 'Other.docx' });
    await act(async () => buttonByText('settings.sources.addChunk')!.click());
    expect(drawer()!.querySelector('input')!.value).toBe('Other.docx');
  });

  it('editing only the title enables Save and sends it', async () => {
    service.getDocumentChunks.mockImplementation(async () =>
      chunksResponse({
        chunks: [
          { doc_id: 'c1', text: 'Body', metadata: { title: 'Old name' } },
        ],
      }),
    );
    service.updateChunk.mockImplementation(async () => ({
      ok: true,
      json: async () => ({ chunk_id: 'c1-new' }),
    }));
    await render({ embedded: true });
    await act(async () => tile()!.click());
    await act(async () => buttonByText('modals.chunk.edit')!.click());
    const title = drawer()!.querySelector('input')!;
    expect(title.value).toBe('Old name');
    expect(buttonByText('modals.chunk.save')!.disabled).toBe(true);
    await act(async () => setFieldValue(title, 'New name'));
    expect(buttonByText('modals.chunk.save')!.disabled).toBe(false);
    await act(async () => buttonByText('modals.chunk.save')!.click());
    expect(service.updateChunk).toHaveBeenCalledWith(
      {
        id: 'doc',
        chunk_id: 'c1',
        text: 'Body',
        metadata: { title: 'New name' },
      },
      null,
    );
  });

  it('saving an untitled chunk sends no empty title', async () => {
    service.updateChunk.mockImplementation(async () => ({
      ok: true,
      json: async () => ({ chunk_id: 'c1-new' }),
    }));
    await render({ embedded: true });
    await act(async () => tile()!.click());
    await act(async () => buttonByText('modals.chunk.edit')!.click());
    await act(async () =>
      setFieldValue(drawer()!.querySelector('textarea')!, 'Rewritten'),
    );
    await act(async () => buttonByText('modals.chunk.save')!.click());
    expect(service.updateChunk).toHaveBeenCalledWith(
      { id: 'doc', chunk_id: 'c1', text: 'Rewritten' },
      null,
    );
  });

  it('an Add drawer opened before the grid lands closes without a discard prompt', async () => {
    let release: () => void = () => undefined;
    const slow = new Promise<void>((resolve) => {
      release = resolve;
    });
    service.getDocumentChunks.mockImplementation(async () => {
      await slow;
      return chunksResponse({
        chunks: [{ doc_id: 'c1', text: 'x', metadata: { title: 'Profile' } }],
      });
    });
    await render({ embedded: true, fileName: 'Carrier.docx' });
    await act(async () => buttonByText('settings.sources.addChunk')!.click());
    expect(drawer()!.querySelector('input')!.value).toBe('Carrier.docx');
    await act(async () => release());
    await act(async () =>
      buttonByText('settings.sources.editor.cancel')!.click(),
    );
    expect(document.body.textContent).not.toContain(
      'settings.sources.editor.discardMessage',
    );
    expect(drawer()).toBeNull();
  });

  /**
   * A 3-chunk store the tests reorder: an update adds the new copy where
   * `placeAt` says (the end by default) and drops the old one.
   */
  const serveStore = (placeAt?: number) => {
    const store = [
      { doc_id: 'c1', text: '# First', metadata: {} },
      { doc_id: 'c2', text: '# Second', metadata: {} },
      { doc_id: 'c3', text: '# Third', metadata: {} },
    ];
    service.getDocumentChunks.mockImplementation(
      async (_id: string, page: number, perPage: number) => {
        const start = (page - 1) * perPage;
        return chunksResponse({
          page,
          per_page: perPage,
          total: store.length,
          chunks: store.slice(start, start + perPage),
        });
      },
    );
    service.updateChunk.mockImplementation(
      async (body: { chunk_id: string; text: string }) => {
        const index = store.findIndex((c) => c.doc_id === body.chunk_id);
        const [old] = store.splice(index, 1);
        const copy = { ...old, doc_id: `${old.doc_id}-new`, text: body.text };
        store.splice(placeAt ?? store.length, 0, copy);
        return { ok: true, json: async () => ({ chunk_id: copy.doc_id }) };
      },
    );
  };

  const editOpenChunk = async (text: string) => {
    await act(async () => buttonByText('modals.chunk.edit')!.click());
    await act(async () =>
      setFieldValue(drawer()!.querySelector('textarea')!, text),
    );
    await act(async () => buttonByText('modals.chunk.save')!.click());
  };

  const position = () =>
    container
      .textContent!.match(/chunkPosition \{"n":(\d+),"total":(\d+)/)!
      .slice(1)
      .map(Number);

  it('an edited chunk the store moved to the end is shown at its new position', async () => {
    serveStore();
    await render({ embedded: true });
    await act(async () => tile()!.click());
    await editOpenChunk('# First edited');
    expect(container.querySelector('h1')?.textContent).toBe('First edited');
    expect(position()).toEqual([3, 3]);
    expect(buttonByLabel('settings.sources.nextChunk')!.disabled).toBe(true);
    // Previous walks the store's current order: nothing is skipped.
    await act(async () =>
      buttonByLabel('settings.sources.previousChunk')!.click(),
    );
    expect(container.querySelector('h1')?.textContent).toBe('Third');
    await act(async () =>
      buttonByLabel('settings.sources.previousChunk')!.click(),
    );
    expect(container.querySelector('h1')?.textContent).toBe('Second');
  });

  it('an edited chunk the store moved off the probed positions keeps its text but not its place', async () => {
    serveStore(1);
    await render({ embedded: true });
    const tiles = container.querySelectorAll<HTMLButtonElement>(
      'button[data-slot="card"]',
    );
    await act(async () => tiles[0].click());
    service.getDocumentChunks.mockClear();
    await editOpenChunk('# First edited');
    expect(container.querySelector('h1')?.textContent).toBe('First edited');
    // Its position is unknown: no number is claimed and paging is off, so
    // previous / next can't step from a place the chunk no longer holds.
    expect(container.textContent).not.toMatch(/chunkPosition \{/);
    expect(container.textContent).toContain('chunkPositionUnplaced');
    expect(buttonByLabel('settings.sources.previousChunk')!.disabled).toBe(
      true,
    );
    expect(buttonByLabel('settings.sources.nextChunk')!.disabled).toBe(true);
    // Only the open and last positions are probed: the whole filtered list
    // (one page of `total`) is never fetched.
    const sizes = service.getDocumentChunks.mock.calls.map(
      (call: unknown[]) => call[2],
    );
    expect(sizes).toContain(1);
    expect(sizes).not.toContain(3);
  });

  it('an edited chunk that keeps its place stays put', async () => {
    serveStore(0);
    await render({ embedded: true });
    await act(async () => tile()!.click());
    await editOpenChunk('# First edited');
    expect(position()).toEqual([1, 3]);
    await act(async () => buttonByLabel('settings.sources.nextChunk')!.click());
    expect(container.querySelector('h1')?.textContent).toBe('Second');
  });

  it('shows a destructive empty state with Retry when the fetch fails', async () => {
    service.getDocumentChunks.mockImplementation(async () => ({ ok: false }));
    await render();
    const alert = container.querySelector('[role="alert"]')!;
    expect(alert).not.toBeNull();
    expect(alert.textContent).toContain('settings.sources.chunkErrors.load');
    expect(tile()).toBeNull();

    service.getDocumentChunks.mockImplementation(async () => chunksResponse());
    await act(async () => buttonByText('retry')!.click());
    expect(tile()).not.toBeNull();
  });
});
