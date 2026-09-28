import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      // The header totals: plural keys joined by the stats key.
      if (key === 'settings.sources.graphrag.view.stats' && opts) {
        return `${opts.entities} · ${opts.relationships}`;
      }
      if (key === 'settings.sources.graphrag.view.entityCount' && opts) {
        return `${opts.formatted} ${opts.count === 1 ? 'entity' : 'entities'}`;
      }
      if (key === 'settings.sources.graphrag.view.relationshipCount' && opts) {
        return `${opts.formatted} ${opts.count === 1 ? 'relationship' : 'relationships'}`;
      }
      return opts && 'count' in opts ? `${key}:${opts.count}` : key;
    },
  }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => null,
  useDispatch: () => vi.fn(),
}));

vi.mock('../../hooks', () => ({
  useDebouncedValue: (value: unknown) => value,
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

// The canvas can't render in the DOM test environment.
vi.mock('react-force-graph-2d', () => ({
  default: () => <canvas data-testid="force-graph" />,
}));

vi.mock('../FileTree', async () => {
  const { createPortal } = await import('react-dom');
  const { useEffect } = await import('react');
  return {
    default: (props: {
      embedded?: boolean;
      initialPath?: string;
      actionsTarget?: HTMLElement | null;
      onCrumbsChange?: (crumbs: { label: string }[]) => void;
    }) => {
      const { onCrumbsChange } = props;
      useEffect(() => {
        onCrumbsChange?.([{ label: 'Key Accounts' }, { label: 'carriers' }]);
      }, [onCrumbsChange]);
      return (
        <div
          data-testid="file-tree"
          data-initial-path={props.initialPath ?? ''}
        >
          {props.embedded ? 'embedded' : 'page'}
          {props.actionsTarget
            ? createPortal(
                <button type="button">ADD FILE</button>,
                props.actionsTarget,
              )
            : null}
        </div>
      );
    },
  };
});
// The embedded chunk list of a source with no folder structure; its "open
// chunk" button reports position 2 like the real list does.
vi.mock('../Chunks', async () => {
  const { useEffect, useState } = await import('react');
  return {
    default: (props: {
      embedded?: boolean;
      documentId: string;
      onOpenChunkChange?: (position: number | 'unplaced' | null) => void;
      controllerRef?: { current: { closeChunk: () => boolean } | null };
    }) => {
      const [open, setOpen] = useState<false | 2 | 'unplaced'>(false);
      const { onOpenChunkChange, controllerRef } = props;
      useEffect(() => {
        onOpenChunkChange?.(open || null);
      }, [open, onOpenChunkChange]);
      if (controllerRef) {
        controllerRef.current = {
          closeChunk: () => {
            setOpen(false);
            return false;
          },
        };
      }
      return (
        <div data-testid="chunks" data-doc={props.documentId}>
          {props.embedded ? 'embedded' : 'page'}
          <button type="button" onClick={() => setOpen(2)}>
            OPEN CHUNK
          </button>
          <button type="button" onClick={() => setOpen('unplaced')}>
            LOSE PLACE
          </button>
        </div>
      );
    },
  };
});
vi.mock('../ConnectorTree', () => ({
  default: () => <div data-testid="connector-tree" />,
}));

vi.mock('../../api/services/userService', () => ({
  default: {
    getSourceGraph: vi.fn(),
    getSourceGraphNodes: vi.fn(),
    getSourceGraphNode: vi.fn(),
  },
}));

import i18next from 'i18next';

import userService from '../../api/services/userService';
import GraphSourceView from './GraphSourceView';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const service = userService as unknown as {
  getSourceGraph: ReturnType<typeof vi.fn>;
  getSourceGraphNodes: ReturnType<typeof vi.fn>;
  getSourceGraphNode: ReturnType<typeof vi.fn>;
};

const ok = (body: unknown) => ({
  ok: true,
  status: 200,
  json: async () => body,
});
const failed = () => ({ ok: false, status: 400, json: async () => ({}) });

const OVERVIEW = {
  nodes: [
    { id: 'a', name: 'Anneke de Vries', type: 'Person', degree: 5 },
    { id: 'b', name: 'Bram', type: 'PERSON', degree: 3 },
    { id: 'n', name: 'Nordhaven', type: 'Company', degree: 9 },
  ],
  edges: [
    { source: 'a', target: 'n', type: 'manages' },
    { source: 'b', target: 'n', type: 'works_for' },
  ],
  stats: { nodes: 371, edges: 1172 },
};

const flush = async () => {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
};

describe('GraphSourceView', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    service.getSourceGraph.mockReset();
    service.getSourceGraphNodes.mockReset();
    service.getSourceGraphNode.mockReset();
    service.getSourceGraph.mockResolvedValue(ok(OVERVIEW));
    service.getSourceGraphNodes.mockResolvedValue(
      ok({
        nodes: [
          {
            id: 'n',
            name: 'Nordhaven',
            type: 'Company',
            degree: 9,
            doc_freq: 4,
          },
        ],
        total: 1,
        page: 1,
        per_page: 25,
        types: [{ key: 'company', label: 'Company', count: 1 }],
      }),
    );
    service.getSourceGraphNode.mockResolvedValue(
      ok({
        node: {
          id: 'n',
          name: 'Nordhaven',
          type: 'Company',
          degree: 9,
          doc_freq: 4,
          relationships: [],
          chunks: [],
        },
      }),
    );
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    sourceType?: string,
    onBack = vi.fn(),
    isNested?: boolean,
  ) => {
    await act(async () => {
      root.render(
        <GraphSourceView
          docId="doc"
          sourceName="Key Accounts"
          sourceType={sourceType}
          isNested={isNested}
          onBackToDocuments={onBack}
          headerAction={<button type="button">Test retrieval</button>}
        />,
      );
    });
    await flush();
  };

  const buttonByText = (text: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === text,
    );

  const openTab = async (label: string) => {
    const tab = Array.from(container.querySelectorAll('[role="tab"]')).find(
      (b) => b.textContent === label,
    ) as HTMLButtonElement;
    await act(async () => {
      tab.dispatchEvent(
        new MouseEvent('mousedown', { bubbles: true, button: 0 }),
      );
    });
    await flush();
  };

  // Bugs row 8: the app language's separators, not the browser's.
  it('formats the graph totals in the app language', async () => {
    const language = i18next.language;
    i18next.language = 'de';
    try {
      await render();
      expect(container.textContent).toContain(
        '371 entities · 1.172 relationships',
      );
    } finally {
      i18next.language = language;
    }
  });

  it('pluralises the graph totals by the raw counts', async () => {
    service.getSourceGraph.mockResolvedValue(
      ok({ ...OVERVIEW, stats: { nodes: 1, edges: 1 } }),
    );
    await render();
    expect(container.textContent).toContain('1 entity · 1 relationship');
  });

  it('heads the view with the whole graph totals and the kind badge', async () => {
    await render();
    const text = container.textContent ?? '';
    expect(text).toContain('Key Accounts');
    expect(text).toContain('settings.sources.graphrag.view.title');
    expect(text).toContain(
      `${(371).toLocaleString()} entities · ${(1172).toLocaleString()} relationships`,
    );
    expect(buttonByText('Test retrieval')).toBeDefined();
    expect(service.getSourceGraph).toHaveBeenCalledWith('doc', null, 100);
  });

  const crumbs = () =>
    Array.from(container.querySelectorAll('[data-slot="breadcrumb-item"]')).map(
      (el) => el.textContent,
    );

  it('crumbs: Sources › the source; the Files tab adds where the tree is', async () => {
    const onBack = vi.fn();
    await render(undefined, onBack);
    expect(crumbs()).toEqual(['settings.sources.label', 'Key Accounts']);
    expect(container.querySelector('.lucide-arrow-left')).toBeNull();

    await openTab('settings.sources.graphrag.view.tabs.files');
    expect(crumbs()).toEqual([
      'settings.sources.label',
      'Key Accounts',
      'carriers',
    ]);

    await openTab('settings.sources.graphrag.view.tabs.graph');
    expect(crumbs()).toEqual(['settings.sources.label', 'Key Accounts']);

    const sources = container.querySelector<HTMLButtonElement>(
      '[data-slot="breadcrumb-link"]',
    )!;
    await act(async () => sources.click());
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('builds the legend from one fold of the loaded types', async () => {
    await render();
    const legend = container.querySelector(
      '[aria-label="settings.sources.graphrag.view.typeFilter"]',
    )!;
    const items = Array.from(legend.querySelectorAll('button')).map(
      (b) => b.textContent,
    );
    // "Person" and "PERSON" fold into one group.
    expect(items).toEqual(['Person2', 'Company1']);
    // xs groups sit in a muted track (DESIGN.md ToggleGroup).
    expect(legend.parentElement!.className).toContain('bg-muted');
  });

  it('reads "Show top [50 | 100 | 250] by connections" at one size, the track holding only the group', async () => {
    await render();
    const limits = buttonByText('100')!.closest('[role="radiogroup"]')!;
    const track = limits.parentElement!;
    expect(track.className).toContain('bg-muted');
    expect(track.textContent).not.toContain(
      'settings.sources.graphrag.view.showTop',
    );
    const label = Array.from(container.querySelectorAll('span')).find(
      (el) => el.textContent === 'settings.sources.graphrag.view.showTop',
    )!;
    expect(label.className).toContain('text-sm');
    expect(label.className).not.toContain('text-xs');
  });

  it('refetches the overview with the chosen size', async () => {
    await render();
    await act(async () => buttonByText('250')!.click());
    await flush();
    expect(service.getSourceGraph).toHaveBeenLastCalledWith('doc', null, 250);
  });

  it('shows the empty state for a graph with no entities', async () => {
    service.getSourceGraph.mockResolvedValue(
      ok({ nodes: [], edges: [], stats: { nodes: 0, edges: 0 } }),
    );
    await render();
    expect(container.textContent).toContain(
      'settings.sources.graphrag.view.empty',
    );
    expect(container.querySelector('[data-testid="force-graph"]')).toBeNull();
  });

  it('shows a retry when the overview fails', async () => {
    service.getSourceGraph.mockResolvedValueOnce(failed());
    await render();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'settings.sources.graphrag.view.loadFailed',
    );
    await act(async () => buttonByText('retry')!.click());
    await flush();
    expect(service.getSourceGraph).toHaveBeenCalledTimes(2);
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('opens an entity from the table and shows it in the graph', async () => {
    await render();
    await openTab('settings.sources.graphrag.view.tabs.entities');
    expect(service.getSourceGraphNodes).toHaveBeenCalledWith(
      'doc',
      { q: undefined, type: undefined, page: 1, perPage: 25 },
      null,
    );
    const row = Array.from(container.querySelectorAll('tbody tr')).find((r) =>
      r.textContent?.includes('Nordhaven'),
    ) as HTMLTableRowElement;
    expect(row.textContent).toContain('Company');
    await act(async () => row.click());
    await flush();
    expect(service.getSourceGraphNode).toHaveBeenCalledWith('doc', 'n', null);

    // One frame, as on the Graph tab: the table and the panel docked beside
    // it (border-l, 40% from xl), the open entity's row marked.
    const openRow = Array.from(container.querySelectorAll('tbody tr')).find(
      (r) => r.textContent?.includes('Nordhaven'),
    ) as HTMLTableRowElement;
    expect(openRow.getAttribute('aria-current')).toBe('true');
    const frame = openRow.closest('[data-slot="card"]')!;
    expect(frame.getAttribute('data-variant')).toBe('subtle');
    expect(frame.className).toContain('h-[70svh]');
    const dock = frame.querySelector('aside')!;
    expect(dock.className).toContain('border-l');
    expect(dock.className).toContain('xl:w-2/5');
    expect(dock.querySelector('h3')?.textContent).toBe('Nordhaven');
    expect(container.querySelector('[data-slot="table-container"]')).toBeNull();
    const close = dock.querySelector(
      'button[aria-label="settings.sources.graphrag.view.close"]',
    )!;
    expect(close.getAttribute('data-size')).toBe('icon-sm');

    await act(async () =>
      buttonByText('settings.sources.graphrag.view.showInGraph')!.click(),
    );
    await flush();
    const graphTab = Array.from(
      container.querySelectorAll('[role="tab"]'),
    ).find(
      (b) => b.textContent === 'settings.sources.graphrag.view.tabs.graph',
    )!;
    expect(graphTab.getAttribute('aria-selected')).toBe('true');
    // The graph tab's docked panel has the node open.
    expect(container.querySelector('aside h3')?.textContent).toBe('Nordhaven');
  });

  it('renders the embedded file view on the Files tab', async () => {
    await render();
    await openTab('settings.sources.graphrag.view.tabs.files');
    expect(
      container.querySelector('[data-testid="file-tree"]')?.textContent,
    ).toBe('embedded');
  });

  it("puts the Files tab's action in the header, only on that tab", async () => {
    await render();
    const addFile = () =>
      Array.from(container.querySelectorAll('button')).find(
        (b) => b.textContent === 'ADD FILE',
      );
    expect(addFile()).toBeUndefined();
    await openTab('settings.sources.graphrag.view.tabs.files');
    const button = addFile();
    expect(button).toBeDefined();
    // It sits in the header, above the tab list, not inside the Files panel.
    const tabList = container.querySelector('[role="tablist"]')!;
    expect(
      button!.compareDocumentPosition(tabList) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      container.querySelector('[data-testid="file-tree"]')?.contains(button!),
    ).toBe(false);
    await openTab('settings.sources.graphrag.view.tabs.graph');
    expect(addFile()).toBeUndefined();
  });

  // A source with no directory structure (one uploaded file) shows its chunk
  // list, as the plain source view does.
  it('shows the embedded chunk list on the Files tab of a flat source', async () => {
    await render(undefined, vi.fn(), false);
    await openTab('settings.sources.graphrag.view.tabs.files');
    const chunks = container.querySelector('[data-testid="chunks"]');
    expect(chunks?.textContent).toContain('embedded');
    expect(chunks?.getAttribute('data-doc')).toBe('doc');
    expect(container.querySelector('[data-testid="file-tree"]')).toBeNull();
    expect(crumbs()).toEqual(['settings.sources.label', 'Key Accounts']);

    // An open chunk adds its crumb; the source crumb closes it.
    await act(async () => buttonByText('OPEN CHUNK')!.click());
    expect(crumbs()).toEqual([
      'settings.sources.label',
      'Key Accounts',
      'settings.sources.chunkCrumb',
    ]);
    const source = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-slot="breadcrumb-link"]',
      ),
    ).find((b) => b.textContent === 'Key Accounts')!;
    await act(async () => source.click());
    expect(crumbs()).toEqual(['settings.sources.label', 'Key Accounts']);

    // A saved chunk whose place is unknown keeps an unnumbered crumb, and the
    // source crumb still closes it.
    await act(async () => buttonByText('LOSE PLACE')!.click());
    expect(crumbs()).toEqual([
      'settings.sources.label',
      'Key Accounts',
      'settings.sources.chunkCrumbUnplaced',
    ]);
    const again = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-slot="breadcrumb-link"]',
      ),
    ).find((b) => b.textContent === 'Key Accounts')!;
    await act(async () => again.click());
    expect(crumbs()).toEqual(['settings.sources.label', 'Key Accounts']);
  });

  it('uses the connector tree for a connector source', async () => {
    await render('connector:file');
    await openTab('settings.sources.graphrag.view.tabs.files');
    expect(
      container.querySelector('[data-testid="connector-tree"]'),
    ).not.toBeNull();
  });

  it("opens a chunk's file on the Files tab from the chunk drawer", async () => {
    service.getSourceGraphNode.mockResolvedValue(
      ok({
        node: {
          id: 'n',
          name: 'Nordhaven',
          type: 'Company',
          degree: 9,
          relationships: [],
          chunks: [
            {
              chunk_id: 'c1',
              text: 'Nordhaven runs the lane.',
              metadata: { source: 'briefs/Nordhaven.md' },
            },
          ],
        },
      }),
    );
    await render();
    await openTab('settings.sources.graphrag.view.tabs.entities');
    const row = Array.from(container.querySelectorAll('tbody tr')).find((r) =>
      r.textContent?.includes('Nordhaven'),
    ) as HTMLTableRowElement;
    await act(async () => row.click());
    await flush();
    const tile = Array.from(
      container.querySelectorAll('button[data-slot="card"]'),
    ).find((b) =>
      b.textContent?.includes('Nordhaven runs the lane.'),
    ) as HTMLButtonElement;
    await act(async () => tile.click());
    const openInFiles = Array.from(
      document.body.querySelectorAll('button'),
    ).find(
      (b) => b.textContent === 'settings.sources.graphrag.view.openInFiles',
    )!;
    await act(async () => openInFiles.click());
    await flush();

    const filesTab = Array.from(
      container.querySelectorAll('[role="tab"]'),
    ).find(
      (b) => b.textContent === 'settings.sources.graphrag.view.tabs.files',
    )!;
    expect(filesTab.getAttribute('aria-selected')).toBe('true');
    expect(
      container
        .querySelector('[data-testid="file-tree"]')
        ?.getAttribute('data-initial-path'),
    ).toBe('briefs/Nordhaven.md');

    // The request is one-off: a later visit opens the tree at its root.
    await openTab('settings.sources.graphrag.view.tabs.entities');
    await openTab('settings.sources.graphrag.view.tabs.files');
    expect(
      container
        .querySelector('[data-testid="file-tree"]')
        ?.getAttribute('data-initial-path'),
    ).toBe('');
  });

  it('a new entity filter fetches page 1 once, not the old page first', async () => {
    service.getSourceGraphNodes.mockImplementation(async () =>
      ok({
        nodes: [{ id: 'n', name: 'Nordhaven', type: 'Company', degree: 9 }],
        total: 60,
        types: [{ type: 'Company', count: 60 }],
      }),
    );
    await render();
    await openTab('settings.sources.graphrag.view.tabs.entities');
    const next = container.querySelector<HTMLButtonElement>(
      'button[aria-label="pagination.nextPage"]',
    )!;
    await act(async () => next.click());
    await flush();
    expect(service.getSourceGraphNodes.mock.lastCall![1].page).toBe(2);
    service.getSourceGraphNodes.mockClear();

    const search = container.querySelector<HTMLInputElement>(
      '[role="tabpanel"][data-state="active"] input',
    )!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    await act(async () => {
      setter.call(search, 'nord');
      search.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await flush();
    const pages = service.getSourceGraphNodes.mock.calls.map(
      (call) => call[1].page,
    );
    expect(pages).toEqual([1]);
  });
});
